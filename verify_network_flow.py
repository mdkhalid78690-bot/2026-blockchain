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


def call(url, timeout=20):
    r = requests.get(url, timeout=timeout)
    print(url, r.status_code)
    try:
        return r.json()
    except Exception:
        return r.text


def call_signed(url, path, timeout=20):
    r = requests.get(url, headers=build_peer_headers(path, timeout=3), timeout=timeout)
    print(url, r.status_code)
    try:
        return r.json()
    except Exception:
        return r.text


def post(url, payload, timeout=20):
    r = requests.post(url, json=payload, timeout=timeout)
    print(url, r.status_code)
    try:
        return r.json()
    except Exception:
        return r.text


def post_signed(url, path, payload=None, timeout=20):
    r = requests.post(url, json=payload, headers=build_peer_headers(path, payload, timeout=3), timeout=timeout)
    print(url, r.status_code)
    try:
        return r.json()
    except Exception:
        return r.text

print('== node health ==')
for node in [NODE1, NODE2]:
    print(call(node + '/healthz'))

print('\n== bootstrap ==')
print(post_signed(NODE1 + '/bootstrap', '/bootstrap', {}))
print(post_signed(NODE2 + '/bootstrap', '/bootstrap', {}))

time.sleep(2)
print('\n== sync chain ==')
print(call_signed(NODE1 + '/sync_chain', '/sync_chain'))
print(call_signed(NODE2 + '/sync_chain', '/sync_chain'))

time.sleep(2)
print('\n== balances before ==')
print(call(NODE1 + '/balance/' + wallet1['address']))
print(call(NODE2 + '/balance/' + wallet2['address']))

balance1 = call(NODE1 + '/balance/' + wallet1['address'])['balance']
if balance1 < 1:
    print('Mining reward on node1 to fund wallet')
    print(call(NODE1 + '/mine'))
    time.sleep(2)
    balance1 = call(NODE1 + '/balance/' + wallet1['address'])['balance']

amount = 1
print('sending amount', amount)
response = post(NODE1 + '/send_transaction', {
    'private_key': wallet1['private_key'],
    'to': wallet2['address'],
    'amount': amount,
    'fee': 0.0,
})
print('tx response', response)

time.sleep(2)
print('\n== mempool after tx ==')
print(call(NODE1 + '/mempool'))
print(call(NODE2 + '/mempool'))

print('\n== mine block on node1 ==')
print(call(NODE1 + '/mine'))

time.sleep(2)
print('\n== balances after ==')
print(call(NODE1 + '/balance/' + wallet1['address']))
print(call(NODE2 + '/balance/' + wallet2['address']))
print(call(NODE1 + '/history/' + wallet2['address']))
print(call(NODE2 + '/history/' + wallet2['address']))
