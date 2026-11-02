import json, time
from pathlib import Path
from types import SimpleNamespace
import api, core

sender = core.create_wallet()
receiver = core.create_wallet()
chain = [core.create_genesis_block()]
reward = core.calculate_reward(len(chain), core.get_total_supply(chain))
prev = chain[-1]
reward_block = {
    'index': len(chain) + 1,
    'timestamp': max(time.time(), float(prev['timestamp'])),
    'transactions': [{
        'transaction': {
            'from': core.NETWORK,
            'to': sender['address'],
            'amount': reward,
            'base_reward': reward,
            'fees': 0,
            'timestamp': time.time(),
        },
        'signature': core.MINING_REWARD_SIGNATURE,
    }],
    'proof': 0,
    'difficulty': core.calculate_next_difficulty(chain),
    'previous_hash': prev['hash'],
}
reward_block['hash'] = core.hash_block(reward_block)
chain.append(reward_block)
confirmed_tx = core.create_signed_transaction(sender['private_key'], receiver['address'], 1, fee=0.1)
confirmed_block = {
    'index': len(chain) + 1,
    'timestamp': time.time(),
    'transactions': [confirmed_tx],
    'proof': 0,
    'difficulty': core.calculate_next_difficulty(chain),
    'previous_hash': chain[-1]['hash'],
}
confirmed_block['hash'] = core.hash_block(confirmed_block)
chain.append(confirmed_block)
next_tx = core.create_signed_transaction(sender['private_key'], receiver['address'], 2, fee=0.1)

# store chain and mempool on disk
Path('blockchain_data.json').write_text(json.dumps(chain, indent=4))
Path('mempool.json').write_text('[]')

# fake healthy peers and signed_get
peer_mempool = [confirmed_tx, next_tx]

def fake_signed_get(url, **kwargs):
    if url.endswith('/mempool'):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: peer_mempool)
    raise AssertionError('Unexpected URL: ' + url)

api.sync_peer_list = lambda: ([], 0, [])
api.healthy_peers = lambda: []
api.load_peers = lambda: ['127.0.0.1:5001']
api.signed_get = fake_signed_get

print('chain length', len(chain))
print('chain txids', [core.tx_id(tx_data) for _block, tx_data, _tx in core.iter_transactions(chain)])
print('peer txids', [core.tx_id(tx) for tx in peer_mempool])
print('known txids pre', {core.tx_id(tx) for tx in []}.union({core.tx_id(tx_data) for _block, tx_data, _tx in core.iter_transactions(chain)}))
res = api.sync_mempool()
print('result', res)
print('saved mempool', Path('mempool.json').read_text())
