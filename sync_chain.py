import requests

response = requests.get(
    "http://127.0.0.1:5000/chain"
, timeout=3)

data = response.json()

print("Blocks:", data["length"])