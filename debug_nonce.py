import json
import time
from decimal import Decimal
import core

sender = core.create_wallet()
receiver = core.create_wallet()
chain = [core.create_genesis_block()]
reward_block = {
    'index': 1,
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

mempool = []
for i in range(1, 21):
    tx = core.create_signed_transaction(sender['private_key'], receiver['address'], 0.01, fee=0.01, chain=chain, mempool=mempool)
    valid, error = core.validate_transaction(tx, chain, mempool)
    balance = core.get_balance(sender['address'], chain, mempool)
    pending = sum(core.tx_spend_amount(core.tx_payload(t)) for t in mempool)
    available = Decimal(str(balance)) - pending
    print('i', i, 'nonce', core.tx_nonce(core.tx_payload(tx)), 'balance', balance, 'pending', pending, 'available', available, 'valid', valid, 'error', error)
    if not valid:
        break
    mempool.append(tx)

print('final mempool size', len(mempool))
print('chain balance', core.get_balance(sender['address'], chain))
print('pending total', sum(core.tx_spend_amount(core.tx_payload(t)) for t in mempool))
