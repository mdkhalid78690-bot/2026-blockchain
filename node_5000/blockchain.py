import hashlib
import json
import secrets
from time import time

def create_wallet():
  return "KWD" + secrets.token_hex(16).upper()

class Blockchain:

    def __init__(self):
        self.chain = []
        self.create_block(proof=1, previous_hash='0')

    def create_block(self, proof, previous_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': str(time()),
            'proof': proof,
            'reward': 50,
            'transactions': [],
            'previous_hash': previous_hash
        }

        self.chain.append(block)
        return block

    def get_previous_block(self):
        return self.chain[-1]

    def hash(self, block):
        encoded = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def proof_of_work(self, previous_proof):
        new_proof = 1
        while True:
            hash_operation = hashlib.sha256(
                str(new_proof**2 - previous_proof**2).encode()
            ).hexdigest()

            if hash_operation[:4] == '0000':
                return new_proof

            new_proof += 1

blockchain = Blockchain()

wallet1 = create_wallet()
wallet2 = create_wallet()

wallet1_balance = 0
wallet2_balance = 0

print("Wallet 1:", wallet1)
print("Wallet 2:", wallet2)

print("My Wallet Address:")
print(wallet1)

MAX_SUPPLY = 7860000
total_supply = 0

while total_supply < MAX_SUPPLY:
    previous_block = blockchain.get_previous_block()
    proof = blockchain.proof_of_work(previous_block['proof'])
    previous_hash = blockchain.hash(previous_block)

    with open("mempool.json", "r") as f:
        transactions = json.load(f)

    block = blockchain.create_block(proof, previous_hash)

    block["transactions"] = transactions

    with open("mempool.json", "w") as f:
        json.dump([], f)

    with open("blockchain_data.json", "w") as f:
        json.dump(blockchain.chain, f, separators=(',', ':'))

    total_supply += block['reward']
    wallet1_balance += block['reward']

    print(
        f"Block {block['index']} mined | "
        f"Reward: {block['reward']} KWD | "
        f"Wallet1 Balance: {wallet1_balance} KWD | "
        f"Total Supply: {total_supply} KWD"
    )
print("\nMaximum supply reached!")
print(f"Total Supply: {total_supply} KWD")

if wallet1_balance >= 100:
    wallet1_balance -= 100
    wallet2_balance += 100

    print("\nTransfer Successful!")
    print("100 KWD sent from Wallet1 to Wallet2")
    print("Wallet1 Balance:", wallet1_balance)
    print("Wallet2 Balance:", wallet2_balance)

    print("\nTransfer Test")

    wallet1_balance -= 100
    wallet2_balance += 100

    print("Wallet1 Balance:", wallet1_balance)
    print("Wallet2 Balance:", wallet2_balance)