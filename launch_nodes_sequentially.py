import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain').resolve()
PORTS = [5000, 5001, 5002, 5003, 5004]


def cleanup_existing_nodes():
    if os.name != 'nt':
        return
    subprocess.run(
        [
            'powershell', '-NoProfile', '-Command',
            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'api.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)


def wait_ready(port: int, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f'http://127.0.0.1:{port}/health', timeout=5)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def get_chain_info(port: int):
    r = requests.get(f'http://127.0.0.1:{port}/chain', timeout=30)
    r.raise_for_status()
    payload = r.json()
    chain = payload.get('chain', []) if isinstance(payload, dict) else payload
    return len(chain), chain[-1].get('hash') if chain and isinstance(chain[-1], dict) else None


cleanup_existing_nodes()

for port in PORTS:
    cfg = {
        'node_id': f'node-{port}',
        'port': port,
        'host': '0.0.0.0',
    }
    (ROOT / 'node_config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    log_path = ROOT / 'logs' / f'node_{port}.log'
    log_path.parent.mkdir(exist_ok=True)
    handle = open(log_path, 'a', encoding='utf-8')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    env['KWD_PORT'] = str(port)
    proc = subprocess.Popen(
        [sys.executable, 'api.py'],
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
    )
    print(f'Starting node on port {port} pid={proc.pid}')
    if wait_ready(port, timeout=60):
        height, tip = get_chain_info(port)
        print(f'port {port}: height={height} tip={tip}')
    else:
        print(f'port {port}: FAILED TO BECOME READY')
    handle.flush()
    time.sleep(2)

print('All startup checks completed.')
