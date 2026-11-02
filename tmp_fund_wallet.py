import json
import pathlib
import requests
from core import create_wallet, read_json, write_json

p = pathlib.Path('wallet1.json')
wallet = create_wallet() if not p.exists() else json.loads(p.read_text())
if not p.exists():
    p.write_text(json.dumps(wallet, indent=4))
wallets = read_json('wallets.json', [])
if not any(item.get('address') == wallet['address'] for item in wallets):
    wallets.append({'wallet': wallet['address'], 'address': wallet['address'], 'public_key': wallet['public_key']})
    write_json('wallets.json', wallets)
print('node1_wallet', wallet['address'])
print(requests.get('http://127.0.0.1:5000/mine', timeout=30).text)
print('balance', requests.get(f'http://127.0.0.1:5000/balance/{wallet["address"]}', timeout=10).text)
