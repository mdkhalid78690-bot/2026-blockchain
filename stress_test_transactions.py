import requests
import threading
import time

URL = "http://127.0.0.1:5000/send_transaction"

PRIVATE_KEY = "9c594538d09cfd5f398f46dfd60acb26d4cdeec7af5d59ae64046791e0d39661"

TO_ADDRESS = "f3b77af047145df0510e7c382aa9ed859feade5b25c159a8a7dd63d4fa84af13"

TOTAL_TRANSACTIONS = int(input("Enter number of transactions: "))

def send_transaction(i):
    payload = {
        "private_key": PRIVATE_KEY,
        "to": TO_ADDRESS,
        "amount": 1
    }

    try:
        response = requests.post(URL, json=payload, timeout=30)
        if response.status_code == 200:
            print(f"✅ {i+1}/{TOTAL_TRANSACTIONS}")
        else:
            print(f"❌ {i+1}/{TOTAL_TRANSACTIONS} -> {response.status_code} : {response.text}")
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    for i in range(TOTAL_TRANSACTIONS):
        send_transaction(i)

    print("Finished sending", TOTAL_TRANSACTIONS, "transactions.")       