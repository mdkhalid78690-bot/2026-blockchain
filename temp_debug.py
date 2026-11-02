import json, time
from pathlib import Path
import core
from core import create_genesis_block
sender = core.create_wallet()
receiver = core.create_wallet()
chain = [create_genesis_block()]
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
print('genesis hash', chain[0]['hash'])
print('reward previous_hash', reward_block['previous_hash'])
print('reward difficulty', reward_block['difficulty'])
print('reward pow hash', __import__('hashlib').sha256(f"{reward_block['previous_hash']}{reward_block['proof']}".encode()).hexdigest())
print('reward valid pow', __import__('hashlib').sha256(f"{reward_block['previous_hash']}{reward_block['proof']}".encode()).hexdigest().startswith('0'*reward_block['difficulty']))
new_block = {
    'index': len(chain) + 1,
    'timestamp': time.time(),
    'transactions': [core.create_signed_transaction(sender['private_key'], receiver['address'], 1, fee=0.1)],
    'proof': 0,
    'difficulty': core.calculate_next_difficulty(chain),
    'previous_hash': chain[-1]['hash'],
}
print('new previous hash', new_block['previous_hash'])
print('new pow hash', __import__('hashlib').sha256(f"{new_block['previous_hash']}{new_block['proof']}".encode()).hexdigest())
print('new valid pow', __import__('hashlib').sha256(f"{new_block['previous_hash']}{new_block['proof']}".encode()).hexdigest().startswith('0'*new_block['difficulty']))
new_block['hash'] = core.hash_block(new_block)
print('new hash', new_block['hash'])
PY