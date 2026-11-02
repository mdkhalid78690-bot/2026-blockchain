import json, os, subprocess, sys, time
from pathlib import Path
import requests
import restart_one_node_scenario as rs

rs.cleanup_stale_nodes()
ROOT = Path('.').resolve()
LOG_DIR = ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)

for port in [5000,5001,5002,5003,5004]:
    log_path = LOG_DIR / f'node_{port}_full_start.log'
    if log_path.exists():
        log_path.unlink()
    proc, handle, runtime = rs.start_node(port, log_path)
    print('started', port, 'pid', proc.pid)
    for attempt in range(30):
        try:
            r = requests.get(f'http://127.0.0.1:{port}/health', timeout=8)
            print('  health', port, attempt, r.status_code, r.text)
            if r.status_code < 500:
                break
        except Exception as exc:
            print('  health_err', port, attempt, repr(exc))
        time.sleep(5)
    else:
        print('  never ready', port)
        print(log_path.read_text(encoding='utf-8', errors='replace')[-8000:])
    time.sleep(2)

print('all done')
