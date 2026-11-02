import json

from core import create_wallet, read_json, write_json


wallet_data = create_wallet()
wallet_number = input("Wallet Number (1,2,3...) : ")

with open(f"wallet{wallet_number}.json", "w") as f:
    json.dump(wallet_data, f, indent=4)

wallets = read_json("wallets.json", [])
public_record = {
    "wallet": wallet_data["address"],
    "address": wallet_data["address"],
    "public_key": wallet_data["public_key"],
}

if not any(item.get("address") == wallet_data["address"] for item in wallets):
    wallets.append(public_record)
    write_json("wallets.json", wallets)

print("\nPRIVATE KEY")
print(wallet_data["private_key"])

print("\nPUBLIC KEY")
print(wallet_data["public_key"])

print("\nADDRESS")
print(wallet_data["address"])
