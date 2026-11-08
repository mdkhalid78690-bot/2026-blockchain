import requests

requests.post(
    "http://127.0.0.1:5001/register_peer",
    json={
        "peer":""
    }
, timeout=3)

print("Done")