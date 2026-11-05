import os, json, requests
import core, api

CLOUD_URL = "https://two026-blockchain.onrender.com"
MINER_WALLET_FILE = "miner_wallet.json"

def get_or_create_miner_wallet(client):
    if os.path.exists(MINER_WALLET_FILE):
        w = json.load(open(MINER_WALLET_FILE, "r", encoding="utf-8"))
        if w.get("address") and w.get("private_key"):
            return w
    print("[Wallet] Generating a brand-new personal KWD Miner Wallet on this computer...")
    resp = client.get("/ wallet/new".replace(" ", ""))
    w = resp.get_json() if resp.status_code == 200 else None
    if not w or not w.get("address"):
        from ecdsa import SigningKey, SECP256k1
        import hashlib
        sk = SigningKey.generate(curve=SECP256k1)
        vk = sk.get_verifying_key()
        priv_hex = sk.to_string().hex()
        pub_hex = vk.to_string().hex()
        addr = hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:40]
        w = {"address": addr, "public_key": pub_hex, "private_key": priv_hex}
    with open(MINER_WALLET_FILE, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=2)
    print(f"[Wallet] Saved your private miner key to {MINER_WALLET_FILE} (NEVER share this file!)")
    return w

def sync_with_cloud():
    local_chain = api.load_chain()
    try:
        resp = requests.get(f"{CLOUD_URL}/chain", timeout=90).json()
        cloud_chain = resp.get("chain", resp) if isinstance(resp, dict) else resp
        if isinstance(cloud_chain, list) and len(cloud_chain) > len(local_chain):
            core.write_json("blockchain_data.json", cloud_chain)
            local_chain = cloud_chain
            print(f" -> Downloaded latest blockchain from cloud (Height: {len(local_chain)})")
        elif isinstance(cloud_chain, list) and len(local_chain) > len(cloud_chain):
            for blk in local_chain[len(cloud_chain):]:
                requests.post(f"{CLOUD_URL}/receive_block", json=blk, timeout=30)
    except Exception as e:
        print(f" -> Cloud sync note: {e}")
    return local_chain

def main():
    client = api.app.test_client()
    wallet = get_or_create_miner_wallet(client)
    miner_addr = wallet["address"]
    print(f"\n==========================================")
    print(f" KawaidCoin (KWD) Standalone CPU Miner")
    print(f" Your Miner Wallet: {miner_addr}")
    print(f"==========================================\n")

    print(f"[1/3] Syncing with live public seed node ({CLOUD_URL})...")
    sync_with_cloud()

    print("\n[2/3] Solving SHA-256 Proof-of-Work on your computer CPU...")
    client.get(f"/mine?miner_address={miner_addr}")
    chain = api.load_chain()
    latest = chain[-1]
    print(f"SUCCESS! Mined Block #{latest.get('index')}!")
    print(f" -> Block Hash : {latest.get('hash')}")
    print(f" -> Difficulty : {latest.get('difficulty')} | Nonce: {latest.get('proof')}")
    print(f" -> Total Supply: {api.get_total_supply(chain)} KWD")

    print("\n[3/3] Broadcasting solved block to global KWD network...")
    try:
        r = requests.post(f"{CLOUD_URL}/receive_block", json=latest, timeout=30)
        print(f" -> Cloud Seed Node Response: HTTP {r.status_code}")
    except Exception as e:
        print(f" -> Saved locally ({e})")

if __name__ == "__main__":
    main()
