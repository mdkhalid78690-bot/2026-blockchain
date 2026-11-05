import os, json, hashlib, requests
from ecdsa import SigningKey, SECP256k1
import core, api

CLOUD_URL = "https://two026-blockchain.onrender.com"
MINER_WALLET_FILE = "miner_wallet.json"

def get_or_create_miner_wallet():
    if os.path.exists(MINER_WALLET_FILE):
        try:
            w = json.load(open(MINER_WALLET_FILE, "r", encoding="utf-8"))
            if len(w.get("address", "")) == 40 and w.get("private_key"):
                return w
        except Exception:
            pass
    print("[Wallet] Generating a brand-new cryptographic KWD Miner Wallet on this computer...")
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.get_verifying_key()
    priv_hex = sk.to_string().hex()
    pub_hex = vk.to_string().hex()
    addr = hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:40]
    w = {"address": addr, "public_key": pub_hex, "private_key": priv_hex}
    with open(MINER_WALLET_FILE, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=2)
    print(f"[Wallet] Saved private key to {MINER_WALLET_FILE} (NEVER share this file!)")
    return w

def main():
    wallet = get_or_create_miner_wallet()
    miner_addr = wallet["address"]
    print(f"\n============================================================")
    print(f" KawaidCoin (KWD) Standalone CPU Miner")
    print(f" Your Personal Miner Address: {miner_addr}")
    print(f"============================================================\n")

    print(f"[1/3] Syncing ledger with live cloud seed node ({CLOUD_URL})...")
    local_chain = api.load_chain()
    try:
        resp = requests.get(f"{CLOUD_URL}/chain", timeout=90).json()
        cloud_chain = resp.get("chain", resp) if isinstance(resp, dict) else resp
        if isinstance(cloud_chain, list) and len(cloud_chain) > len(local_chain):
            core.write_json("blockchain_data.json", cloud_chain)
            local_chain = cloud_chain
    except Exception as e:
        print(f" -> Cloud sync note: {e}")

    print("\n[2/3] Solving SHA-256 Proof-of-Work on your laptop CPU...")
    # Temporarily route mining reward to miner_wallet.json and pause offline local peer checks
    w1_backup = open("wallet1.json", "r", encoding="utf-8").read() if os.path.exists("wallet1.json") else None
    peers_backup = open("peers.json", "r", encoding="utf-8").read() if os.path.exists("peers.json") else None
    try:
        with open("wallet1.json", "w", encoding="utf-8") as f:
            json.dump(wallet, f, indent=2)
        if peers_backup is not None:
            with open("peers.json", "w", encoding="utf-8") as f:
                f.write("[]")
        client = api.app.test_client()
        client.get("/mine")
    finally:
        if w1_backup is not None:
            open("wallet1.json", "w", encoding="utf-8").write(w1_backup)
        if peers_backup is not None:
            open("peers.json", "w", encoding="utf-8").write(peers_backup)

    chain = api.load_chain()
    latest = chain[-1]
    reward_to = latest["transactions"][0]["transaction"].get("to")
    print(f"SUCCESS! Laptop CPU mined Block #{latest.get('index')}!")
    print(f" -> Block Hash  : {latest.get('hash')}")
    print(f" -> Reward Paid : 50 KWD -> {reward_to}")
    print(f" -> Difficulty  : {latest.get('difficulty')} | Nonce: {latest.get('proof')}")
    print(f" -> Total Supply: {api.get_total_supply(chain)} KWD")

    print("\n[3/3] Broadcasting solved block to live cloud seed node...")
    try:
        r = requests.post(f"{CLOUD_URL}/receive_block", json=latest, timeout=30)
        print(f" -> Cloud Seed Node Response: HTTP {r.status_code}")
    except Exception as e:
        print(f" -> Saved locally ({e})")

if __name__ == "__main__":
    main()
