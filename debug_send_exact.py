import json
import time
import core
from pathlib import Path

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

print('sender', sender['address'])
print('balance', core.get_balance(sender['address'], chain))
print('supply', core.get_total_supply(chain))
print('reward', core.calculate_reward(len(chain)-1, core.get_total_supply(chain)-core.calculate_reward(len(chain)-1, core.get_total_supply(chain))))

tx = core.create_signed_transaction(sender['private_key'], receiver['address'], 0.01, fee=0.01, chain=chain, mempool=[])
print('tx', tx)
print('validate', core.validate_transaction(tx, chain, []))
print('nonce expected', core.get_next_nonce(sender['address'], chain, []))
print('spent', core.tx_spend_amount(core.tx_payload(tx)))
print('pending balance', core.get_balance(sender['address'], chain, []))
