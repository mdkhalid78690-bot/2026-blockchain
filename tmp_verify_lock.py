import os
import sys
from pathlib import Path

try:
    import psutil
except Exception as exc:
    print('psutil_unavailable', exc)
    sys.exit(0)

root = Path(r'c:/Users/MD khalid/Desktop/2026 blockchain')
files_to_check = ['chain_config.json', 'blockchain_data.json', 'mempool.json', 'peers.json', 'node_config.json']

print('Scanning python.exe processes serving api.py...')
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.info['name'] != 'python.exe':
            continue
        cmd = ' '.join(proc.info['cmdline'] or [])
        if 'api.py' not in cmd:
            continue
        print('PID', proc.info['pid'], 'CMD', cmd)
        try:
            for f in proc.open_files():
                path = str(f.path)
                if any(target in path for target in files_to_check):
                    print('  OPEN', path)
        except Exception as exc:
            print('  open_files_error', exc)
    except Exception:
        pass

runtime = root / 'node_5002'
for name in files_to_check:
    path = runtime / name
    if path.exists():
        temp = path.with_suffix(path.suffix + '.tmp')
        print('TRY_REPLACE', path)
        try:
            with open(temp, 'w', encoding='utf-8') as fh:
                fh.write('test')
            os.replace(temp, path)
            print('  replace_ok')
        except Exception as exc:
            print('  replace_error', repr(exc))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
