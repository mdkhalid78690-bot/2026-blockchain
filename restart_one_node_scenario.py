import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests


def cleanup_stale_nodes():
    if os.name != 'nt':
        return
    try:
        subprocess.run(
            [
                'powershell', '-NoProfile', '-Command',
                "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'api.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


ROOT = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain').resolve()
PORTS = [5000, 5001, 5002, 5003, 5004]
LOG_DIR = ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)


def prepare_node_runtime_dir(base_dir: Path, port: int) -> Path:
    runtime_dir = base_dir / f'node_{port}'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    source_dir = ROOT
    if base_dir != ROOT:
        source_dir = base_dir
    for name in [
        'api.py',
        'core.py',
        'blockchain.py',
        'transaction.py',
        'wallet.py',
        'blockchain_data.json',
        'mempool.json',
        'public_keys.json',
        'wallets.json',
        'wallet_secrets.json',
        'peers.json',
        'blacklisted_peers.json',
        'peer_failures.json',
        'peer_reputations.json',
        'chain_config.json',
        'node_config.json',
        'blockchain_state.sqlite3',
        'node_events.json',
        'audit_log.json',
        'approval_history.json',
    ]:
        src = source_dir / name
        dst = runtime_dir / name
        if src.exists():
            if src.is_file():
                dst.write_bytes(src.read_bytes())
            else:
                shutil.copytree(src, dst, dirs_exist_ok=True)
    config = {'node_id': f'node-{port}', 'port': port, 'host': '0.0.0.0'}
    (runtime_dir / 'node_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    return runtime_dir


def write_node_config(port: int):
    config = {'node_id': f'node-{port}', 'port': port, 'host': '0.0.0.0'}
    (ROOT / 'node_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')


def wait_ready(port: int, timeout: int = 900, request_timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f'http://127.0.0.1:{port}/health', timeout=request_timeout)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        if port in {5003, 5004}:
            time.sleep(10)
        else:
            time.sleep(2)
    return False


def get_chain_info(port: int, timeout: int = 180):
    response = requests.get(f'http://127.0.0.1:{port}/chain', timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    chain = payload.get('chain', []) if isinstance(payload, dict) else payload
    tip = chain[-1].get('hash') if chain and isinstance(chain[-1], dict) else None
    return len(chain), tip


def wait_chain_ready(port: int, timeout: int = 900, request_timeout: int = 180, poll_interval: int = 5):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            return get_chain_info(port, timeout=request_timeout)
        except Exception as exc:
            last_error = exc
            time.sleep(poll_interval)
    raise RuntimeError(f'node on port {port} did not report chain data in time: {last_error}')


def start_node(port: int, log_path: Path):
    runtime_dir = prepare_node_runtime_dir(ROOT, port)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    env['KWD_PORT'] = str(port)
    handle = log_path.open('a', encoding='utf-8')
    proc = subprocess.Popen(
        [sys.executable, 'api.py'],
        cwd=str(runtime_dir),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
    )
    return proc, handle, runtime_dir


def stop_node(proc: subprocess.Popen):
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=20)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main():
    procs = []
    handles = []
    try:
        cleanup_stale_nodes()
        time.sleep(2)

        print('Starting nodes sequentially...')
        for port in PORTS:
            log_path = LOG_DIR / f'node_{port}.log'
            proc, handle, runtime_dir = start_node(port, log_path)
            procs.append((port, proc))
            handles.append(handle)
            print(f'started port {port} pid={proc.pid} runtime={runtime_dir}')
            if not wait_ready(port, timeout=900, request_timeout=30):
                raise RuntimeError(f'node on port {port} did not become ready')
            height, tip = wait_chain_ready(port, timeout=900, request_timeout=180)
            print(f'  port {port}: height={height} tip={tip}')
            time.sleep(2)

        print('Baseline heights before restart:')
        baseline = {port: wait_chain_ready(port, timeout=900, request_timeout=180) for port in PORTS}
        for port, (height, tip) in baseline.items():
            print(f'  port {port}: height={height} tip={tip}')

        target_port = 5003
        target_proc = None
        for port, proc in procs:
            if port == target_port:
                target_proc = proc
                break
        if target_proc is None:
            raise RuntimeError('target node process not found')

        print(f'Stopping node on port {target_port}...')
        stop_node(target_proc)
        time.sleep(5)

        print(f'Restarting node on port {target_port}...')
        log_path = LOG_DIR / 'node_5003_restart.log'
        proc, handle, runtime_dir = start_node(target_port, log_path)
        procs = [(port, proc if port == target_port else existing_proc) for port, existing_proc in procs]
        handles.append(handle)
        print(f'  restarted runtime={runtime_dir}')
        if not wait_ready(target_port, timeout=900, request_timeout=30):
            raise RuntimeError('restarted node did not become ready')

        time.sleep(10)
        print('Heights after restart:')
        after_restart = {}
        for port in PORTS:
            try:
                after_restart[port] = wait_chain_ready(port, timeout=900, request_timeout=180)
                print(f'  port {port}: height={after_restart[port][0]} tip={after_restart[port][1]}')
            except Exception as exc:
                print(f'  port {port}: error {exc}')
                after_restart[port] = (None, None)

        expected_height = after_restart[target_port][0]
        mismatches = [port for port in PORTS if after_restart[port][0] != expected_height or after_restart[port][1] != after_restart[target_port][1]]
        if mismatches:
            print(f'chain recovery verification failed for ports: {mismatches}')
            raise RuntimeError(f'chain recovery verification failed for ports: {mismatches}')

        print('Recovery verification passed: all nodes report the same height and tip hash after restart.')
    finally:
        for _, proc in procs:
            stop_node(proc)
        for handle in handles:
            try:
                handle.flush()
                handle.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
