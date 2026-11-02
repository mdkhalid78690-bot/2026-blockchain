import json

with open("wallet1.json", "r") as f:
    wallet1 = json.load(f)

reward = 50

print("Miner:", wallet1["address"])
print("Mining Reward:", reward, "KWD")