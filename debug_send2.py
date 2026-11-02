import json
import time
import api
import core
from pathlib import Path

backup_chain = Path('blockchain_data.json').read_text() if Path('blockchain_data.json').exists() else None
backup_mempool = Path('mempool.json').read_text() if Path('mempool.json').exists() else None
backup_public = Path('public_keys.json').read_text() if Path('public_keys.json').exists() else None
try:
    wallet = core.create_wallet()
    receiver = core.create_wallet()
    chain = [core.create_genesis_block()]
    reward_block = {
        'index': len(chain) + 1,
        'timestamp': max(time.time(), float(chain[-1]['timestamp'])),
        'transactions': [{
            'transaction': {
                'from': core.NETWORK,
                'to': wallet['address'],
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
    Path('public_keys.json').write_text('[]')
    client = api.app.test_client()
    for i in range(1, 201):
        response = client.post(
            '/send_transaction',
            json={
                'private_key': wallet['private_key'],
                'to': receiver['address'],
                'amount': 0.01,
                'fee': 0.01,
            },
        )
        print(i, response.status_code, response.get_data(as_text=True))
        if response.status_code != 200:
            break
finally:
    if backup_chain is not None:
        Path('blockchain_data.json').write_text(backup_chain)
    if backup_mempool is not None:
        Path('mempool.json').write_text(backup_mempool)
    if backup_public is not None:
        Path('public_keys.json').write_text(backup_public)
