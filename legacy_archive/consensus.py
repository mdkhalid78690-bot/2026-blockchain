import json
import requests

with open("blockchain_data.json", "r") as f:
    my_chain = json.load(f)

my_length = len(my_chain)

with open("peers.json", "r") as f:
    peers = json.load(f)

best_chain = my_chain

for peer in peers:

    try:

        response = requests.get(
            peer + "/chain"
        )

        data = response.json()

        peer_chain = data["chain"]

        if len(peer_chain) > len(best_chain):

            print(
                "Found longer chain:",
                len(peer_chain)
            )

            best_chain = peer_chain

    except:

        print(
            "Peer offline:",
            peer
        )

if len(best_chain) > my_length:

    with open(
        "blockchain_data.json",
        "w"
    ) as f:

        json.dump(
            best_chain,
            f,
            indent=4
        )

    print("Chain updated")

else:

    print("Already longest chain")