import json

wallet = input("Enter Wallet Address: ")

with open("blockchain_data.json", "r") as f:
    chain = json.load(f)

print("\nTRANSACTIONS\n")

found = False

for block in chain:
    for tx in block.get("transactions", []):

        if isinstance(tx, dict) and "transaction" in tx:
            transaction = tx["transaction"]

            if (
                transaction["from"] == wallet
                or transaction["to"] == wallet
            ):
                print("FROM  :", transaction["from"])
                print("TO    :", transaction["to"])
                print("AMOUNT:", transaction["amount"])
                print("-" * 40)
                
                found = True

if not found:
    print("NO TRANSACTIONS FOUND")