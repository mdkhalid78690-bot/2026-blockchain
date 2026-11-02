import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain').resolve()
BASE = ROOT.parent
NODE_DIRS = [
    ROOT,
    BASE / '2026 blockchain node2',
    BASE / '2026 blockchain node3',
    BASE / '2026 blockchain node4',
    BASE / '2026 blockchain node5',
]
PORTS = [5000, 5001, 5002, 5003, 5004]
LOG_DIR = ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)


def wait_ready(port, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f'http://127.0.0.1:{port}/health', timeout=2)
            if resp.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def get_length(port):
    try:
        resp = requests.get(f'http://127.0.0.1:{port}/chain', timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        chain = payload.get('chain', []) if isinstance(payload, dict) else payload
        return len(chain)
    except Exception as exc:
        return f'error:{exc}'


procs = []
for idx, node_dir in enumerate(NODE_DIRS):
    port = PORTS[idx]
    log_path = LOG_DIR / f'node{idx + 1}.log'
    with log_path.open('a', encoding='utf-8') as handle:
        proc = subprocess.Popen([sys.executable, 'api.py'], cwd=str(node_dir), stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        procs.append((port, proc))
        print(f'started {port} pid={proc.pid}')
    ready = wait_ready(port, timeout=45)
    print(f'port {port} ready={ready}')

try:
    for port in PORTS:
        print(f'port {port} length={get_length(port)}')
finally:
    for port, proc in procs:
        if proc.poll() is None:
            if os.name == 'nt':
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
