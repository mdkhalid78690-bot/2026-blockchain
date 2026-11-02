import json
import time
from pathlib import Path
import core

# Setup chain and txs
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
print('confirmed_tx_nonce', confirmed_tx['transaction']['nonce'])
print('next_tx_nonce', next_tx['transaction']['nonce'])
print('confirmed_txid', core.tx_id(confirmed_tx))
print('next_txid', core.tx_id(next_tx))
print('chain txids', [core.tx_id(tx_data) for _block, tx_data, _tx in core.iter_transactions(chain)])
known_txids = {core.tx_id(tx) for tx in []}
known_txids.update({core.tx_id(tx_data) for _block, tx_data, _tx in core.iter_transactions(chain)})
print('known txids', known_txids)
print('confirmed in known', core.tx_id(confirmed_tx) in known_txids)
print('next nonce expected', core.get_next_nonce(sender['address'], chain, []))
valid, error = core.validate_transaction(confirmed_tx, chain, [])
print('validate_confirmed', valid, error)
valid2, error2 = core.validate_transaction(next_tx, chain, [])
print('validate_next', valid2, error2)
