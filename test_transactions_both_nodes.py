import json
import time
import requests
from pathlib import Path
from api import build_peer_headers

ROOT = Path('c:/Users/MD khalid/Desktop/2026 blockchain')
NODE1 = ""
NODE2 = ""
NODE2_DIR = Path('c:/Users/MD khalid/Desktop/2026 blockchain node2')

with open(ROOT / 'wallet1.json', 'r', encoding='utf-8') as fh:
    wallet1 = json.load(fh)
with open(NODE2_DIR / 'wallet2.json', 'r', encoding='utf-8') as fh:
    wallet2 = json.load(fh)


def get_json(url, timeout=20):
    r = requests.get(url, timeout=timeout)
    return r.status_code, r.json() if 'application/json' in r.headers.get('content-type', '') else r.text


def post_json(url, payload, timeout=20):
    r = requests.post(url, json=payload, timeout=timeout)
    return r.status_code, r.json() if 'application/json' in r.headers.get('content-type', '') else r.text


def print_state(label):
    print(f'== {label} ==')
    for base in [NODE1, NODE2]:
        status, data = get_json(base + '/mempool')
        print(base, 'mempool', status, data)
        status, data = get_json(base + '/balance/' + wallet2['address'])
        print(base, 'balance', status, data)
        status, data = get_json(base + '/latest_block')
        print(base, 'latest_block', status, data.get('index') if isinstance(data, dict) else data)
    print()

print_state('before')

status, tx_resp = post_json(NODE1 + '/send_transaction', {
    'private_key': wallet1['private_key'],
    'to': wallet2['address'],
    'amount': 1,
    'fee': 0.0,
})
print('send_transaction', status, tx_resp)

time.sleep(2)
print_state('after send')

status, mine_resp = get_json(NODE1 + '/mine')
print('mine', status, mine_resp)

time.sleep(2)
print_state('after mine')
