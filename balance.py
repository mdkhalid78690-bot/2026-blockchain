import json

wallet_address = input("Enter Wallet Address: ")

balance = 0

with open("blockchain_data.json", "r") as f:
    chain = json.load(f)

for block in chain:

    if "transactions" in block:
        
        for tx in block["transactions"]:

            if "transaction" in tx:
                transaction = tx["transaction"]
            else:
                transaction = tx

            if transaction["to"] == wallet_address:
                balance += transaction["amount"]

            if transaction["from"] == wallet_address:
                balance -= transaction["amount"]

print("\nBalance:", balance, "KWD")