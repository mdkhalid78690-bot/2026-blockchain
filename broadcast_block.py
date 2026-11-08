import json
import requests

with open("blockchain_data.json", "r") as f:
    chain = json.load(f)

last_block = chain[-1]

with open("peers.json", "r") as f:
    peers = json.load(f)

for peer in peers:
    try:
        response = requests.post(
            f"{peer}/receive_block",
            json=last_block
        , timeout=3)
        print(f"Broadcasted block to {peer}")
    except Exception as e:
        print(f"Failed to send to {peer}: {e}")