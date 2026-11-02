import time
from pathlib import Path
import requests
import restart_one_node_scenario as rs

rs.cleanup_stale_nodes()
time.sleep(2)
proc, handle, runtime = rs.start_node(5004, Path('logs/node_5004_probe.log'))
print('pid', proc.pid)
for i in range(60):
    try:
        response = requests.get('http://127.0.0.1:5004/health', timeout=10)
        print('attempt', i, 'status', response.status_code, 'body', response.text)
        if response.status_code < 500:
            print('ready')
            break
    except Exception as exc:
        print('attempt', i, 'error', repr(exc))
    time.sleep(2)
else:
    print('never ready')

print('proc poll', proc.poll())
print('tail')
print(Path('logs/node_5004_probe.log').read_text(encoding='utf-8', errors='replace')[-4000:])
rs.stop_node(proc)
handle.close()
