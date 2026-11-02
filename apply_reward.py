import json

with open("wallet1.json", "r") as f:
    wallet1 = json.load(f)

reward_tx = {
    "transaction": {
        "from": "NETWORK",
        "to": wallet1["address"],
        "amount": 50
    },
    "signature": "MINING_REWARD"
}

with open("mempool.json", "r") as f:
    mempool = json.load(f)

mempool.append(reward_tx)

with open("mempool.json", "w") as f:
    json.dump(mempool, f, indent=4)

print("Mining reward added to mempool")