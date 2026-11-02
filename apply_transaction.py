import json

with open("balances.json", "r") as f:
    balances = json.load(f)

amount = 100

if balances["wallet1"] >= amount:

    balances["wallet1"] -= amount

    balances["wallet2"] += amount

    with open("balances.json", "w") as f:
        json.dump(balances, f, indent=4)

    print("Transaction Applied!")

else:
    print("Insufficient Balance")