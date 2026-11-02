import time
from pathlib import Path
import requests
import restart_one_node_scenario as rs

rs.cleanup_stale_nodes()
time.sleep(2)
for port in [5000, 5001, 5002, 5003, 5004]:
    print('starting', port)
    proc, handle, runtime = rs.start_node(port, Path(f'logs/node_{port}_probe.log'))
    print('pid', port, proc.pid)
    ready = rs.wait_ready(port, timeout=180)
    print('ready', port, ready)
    if not ready:
        print('poll', port, proc.poll())
        print('log tail', Path(f'logs/node_{port}_probe.log').read_text(encoding='utf-8', errors='replace')[-4000:])
    time.sleep(2)

print('done')
