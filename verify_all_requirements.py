import json
import pathlib
import requests
import sys
from api import build_peer_headers

ROOT = pathlib.Path('c:/Users/MD khalid/Desktop/2026 blockchain')
NODE2_DIR = pathlib.Path('c:/Users/MD khalid/Desktop/2026 blockchain node2')
NODE1 = ""
NODE2 = ""

with open(ROOT / 'wallet1.json', 'r', encoding='utf-8') as fh:
    wallet1 = json.load(fh)
with open(NODE2_DIR / 'wallet2.json', 'r', encoding='utf-8') as fh:
    wallet2 = json.load(fh)

print('build_peer_headers', build_peer_headers('/bootstrap'))

cfg1 = json.loads((ROOT / 'chain_config.json').read_text(encoding='utf-8'))
cfg2 = json.loads((NODE2_DIR / 'chain_config.json').read_text(encoding='utf-8'))
sec1 = cfg1.get('security', {})
sec2 = cfg2.get('security', {})
print('config_match', {
    'peer_shared_secret': sec1.get('peer_shared_secret') == sec2.get('peer_shared_secret'),
    'peer_registration_token': cfg1.get('peer_registration_token') == cfg2.get('peer_registration_token'),
    'network_id': cfg1.get('network_id') == cfg2.get('network_id'),
    'rate_limit': sec1.get('rate_limit') == sec2.get('rate_limit'),
    'tls_enabled': sec1.get('tls_enabled') == sec2.get('tls_enabled'),
    'monitoring_enabled': sec1.get('monitoring_enabled') == sec2.get('monitoring_enabled'),
})

for base, addr in [(NODE1, wallet1['address']), (NODE2, wallet2['address'])]:
    r = requests.get(f'{base}/balance/{addr}', timeout=10)
    print('balance', base, r.status_code, r.json())

for base in [NODE1, NODE2]:
    for path in ['/bootstrap', '/sync_chain', '/sync_peers']:
        r = requests.get(base + path, headers=build_peer_headers(path, timeout=3), timeout=20)
        print('sync', base, path, r.status_code, r.json())

send = requests.post(NODE1 + '/send_transaction', json={
    'private_key': wallet1['private_key'],
    'to': wallet2['address'],
    'amount': 1,
    'fee': 0.0,
}, timeout=20)
print('send_transaction', send.status_code, send.json())

for base in [NODE1, NODE2]:
    r = requests.get(base + '/mempool', timeout=10)
    print('mempool', base, r.status_code, r.json())

mine = requests.get(NODE1 + '/mine', timeout=30)
print('mine', mine.status_code, mine.json())

for base in [NODE1, NODE2]:
    r = requests.get(base + '/balance/' + wallet2['address'], timeout=10)
    print('recipient_balance', base, r.status_code, r.json())
    r = requests.get(base + '/latest_block', timeout=10)
    print('latest_block', base, r.status_code, r.json().get('index'))
