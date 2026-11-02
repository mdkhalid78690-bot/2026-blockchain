import requests
from api import build_peer_headers

nodes = ['http://127.0.0.1:5000', 'http://127.0.0.1:5001']
for base in nodes:
    for path in ['/bootstrap', '/sync_chain', '/sync_peers']:
        try:
            r = requests.get(base + path, headers=build_peer_headers(path), timeout=20)
            print(base, path, r.status_code)
            print(r.text)
        except Exception as exc:
            print(base, path, 'ERR', exc)
        print('---')
