import json
import time
from pathlib import Path
import core
import api

sender = core.create_wallet()
receiver = core.create_wallet()
chain = [core.create_genesis_block()]
reward_block = {
    'index': len(chain) + 1,
    'timestamp': max(time.time(), float(chain[-1]['timestamp'])),
    'transactions': [{
        'transaction': {
            'from': core.NETWORK,
            'to': sender['address'],
            'amount': core.calculate_reward(len(chain), core.get_total_supply(chain)),
            'base_reward': core.calculate_reward(len(chain), core.get_total_supply(chain)),
            'fees': 0,
            'timestamp': time.time(),
        },
        'signature': core.MINING_REWARD_SIGNATURE,
    }],
    'proof': 0,
    'difficulty': core.calculate_next_difficulty(chain),
    'previous_hash': chain[-1]['hash'],
}
reward_block['hash'] = core.hash_block(reward_block)
chain.append(reward_block)
Path('blockchain_data.json').write_text(json.dumps(chain, indent=4))
Path('mempool.json').write_text('[]')
print('load_chain', api.load_chain())
print('get_balance', core.get_balance(sender['address'], api.load_chain()))
print('load_mempool', api.load_mempool())
