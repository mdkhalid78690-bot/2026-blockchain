import json
import requests

with open("peers.json", "r") as f:
    peers = json.load(f)

with open("mempool.json", "r") as f:
    mempool = json.load(f)

latest_tx = mempool[-1]

for peer in peers:

    try:

        requests.post(
            peer + "/receive_transaction",
            json=latest_tx
        )

        print(
            "Broadcasted transaction to",
            peer
        )

    except:

        print(
            "Peer offline:",
            peer
        )