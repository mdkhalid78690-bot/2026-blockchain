import json
import time
import api
import core
from pathlib import Path

backup_chain = Path('blockchain_data.json').read_text() if Path('blockchain_data.json').exists() else None
backup_mempool = Path('mempool.json').read_text() if Path('mempool.json').exists() else None
try:
    chain = [core.create_genesis_block()]
    reward = core.calculate_reward(len(chain), core.get_total_supply(chain))
    prev = chain[-1]
    reward_block = {
        'index': len(chain) + 1,
        'timestamp': max(time.time(), float(prev['timestamp'])),
        'transactions': [{
            'transaction': {
                'from': core.NETWORK,
                'to': 'miner',
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
    Path('blockchain_data.json').write_text(json.dumps(chain, indent=4))
    Path('mempool.json').write_text('[]')
    sender = core.create_wallet()
    receiver = core.create_wallet()
    client = api.app.test_client()
    for i in range(1, 21):
        res = client.post(
            '/send_transaction',
            json={
                'private_key': sender['private_key'],
                'to': receiver['address'],
                'amount': 0.01,
                'fee': 0.01,
            },
        )
        print(i, res.status_code, res.get_data(as_text=True))
        if res.status_code != 200:
            break
finally:
    if backup_chain is not None:
        Path('blockchain_data.json').write_text(backup_chain)
    if backup_mempool is not None:
        Path('mempool.json').write_text(backup_mempool)
