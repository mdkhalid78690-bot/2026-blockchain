import requests

requests.post(
    "http://127.0.0.1:5001/register_peer",
    json={
        "peer":"http://127.0.0.1:5000"
    }
)

print("Done")