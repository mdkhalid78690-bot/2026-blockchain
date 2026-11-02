import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain').resolve()
PORTS = [5000, 5001, 5002, 5003, 5004]
LOG_DIR = ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Stop any existing api.py processes on Windows before starting fresh.
if os.name == 'nt':
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

procs = []
for port in PORTS:
    cfg = {
        'node_id': f'node-{port}',
        'port': port,
        'host': '0.0.0.0',
    }
    (ROOT / 'node_config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    log_path = LOG_DIR / f'node_{port}.log'
    handle = open(log_path, 'a', encoding='utf-8')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, 'api.py'],
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
    )
    procs.append((port, proc, handle))
    print(f'Started node on port {port} pid={proc.pid}')
    time.sleep(3)

print('Waiting for nodes to boot...')
time.sleep(10)

for port, proc, handle in procs:
    print(f'port {port} alive={proc.poll() is None}')
    if handle is not None:
        handle.flush()

print('Done. Nodes are running in background.')
