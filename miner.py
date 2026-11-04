import requests
import core
import api

CLOUD_URL = "https://two026-blockchain.onrender.com"

def sync_missing_blocks_to_cloud(local_chain):
    try:
        resp = requests.get(f"{CLOUD_URL}/chain", timeout=90).json()
        cloud_chain = resp.get("chain", resp) if isinstance(resp, dict) else resp
        cloud_len = len(cloud_chain) if isinstance(cloud_chain, list) else 0
    except Exception as e:
        print(f"Cloud waking up ({e})...")
        return

    if len(local_chain) > cloud_len:
        print(f"Uploading {len(local_chain) - cloud_len} missing block(s) to cloud in order...")
        for blk in local_chain[cloud_len:]:
            r = requests.post(f"{CLOUD_URL}/receive_block", json=blk, timeout=30)
            print(f" -> Sent Block #{blk.get('index')}: status {r.status_code}")

def main():
    print(f"[1/3] Checking live cloud seed node ({CLOUD_URL})...")
    local_chain = api.load_chain()
    sync_missing_blocks_to_cloud(local_chain)

    print("\n[2/3] Mining new block on YOUR LAPTOP CPU (SHA-256 Proof-of-Work)...")
    client = api.app.test_client()
    client.get("/mine")

    chain = api.load_chain()
    latest = chain[-1]
    print(f"SUCCESS! Laptop CPU mined Block #{latest.get('index')}!")
    print(f" -> Block Hash : {latest.get('hash')}")
    print(f" -> Merkle Root: {latest.get('merkle_root')}")
    print(f" -> Difficulty : {latest.get('difficulty')}")
    print(f" -> Nonce/Proof: {latest.get('proof')}")
    print(f" -> Total Supply: {api.get_total_supply(chain)} KWD")

    print("\n[3/3] Broadcasting solved block to live cloud server...")
    sync_missing_blocks_to_cloud(chain)

if __name__ == "__main__":
    main()
