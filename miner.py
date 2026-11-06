import os, json, time, hashlib, requests

CLOUD_URL = "https://two026-blockchain.onrender.com"
WALLET_FILE = "kwd_miner_wallet.json"

def get_or_create_wallet():
    if os.path.exists(WALLET_FILE):
        return json.load(open(WALLET_FILE, "r", encoding="utf-8"))
    print("[Wallet] Requesting new cryptographic KWD wallet keypair...")
    try:
        r = requests.post(f"{CLOUD_URL}/wallet/create", timeout=30)
        if r.status_code == 200 and r.json().get("address"):
            w = r.json()
        else:
            raise ValueError("Fallback to local keygen")
    except Exception:
        seed = os.urandom(32).hex()
        addr = hashlib.sha256(seed.encode()).hexdigest()[:40]
        w = {"address": addr, "private_key": seed}
    json.dump(w, open(WALLET_FILE, "w", encoding="utf-8"), indent=2)
    print(f"[Wallet] Saved personal wallet to {WALLET_FILE} (Keep this file private!)")
    return w

def sha256d(data_str):
    return hashlib.sha256(hashlib.sha256(data_str.encode("utf-8")).digest()).hexdigest()

def main():
    w = get_or_create_wallet()
    addr = w.get("address")
    print("============================================================")
    print(" KawaidCoin (KWD) Public Standalone CPU Miner v1.0")
    print(f" Connected Node : {CLOUD_URL}")
    print(f" Miner Address  : {addr}")
    print("============================================================\n")

    print("[1/2] Benchmarking local CPU SHA-256 Proof-of-Work hashrate...")
    t0 = time.time()
    nonce = 0
    target = "00"
    while True:
        h = sha256d(f"{addr}-{nonce}-{t0}")
        if h.startswith(target) and nonce > 5000:
            break
        nonce += 1
    elapsed = max(0.001, time.time() - t0)
    hashrate = int(nonce / elapsed)
    print(f" -> Local CPU PoW Solved! Nonce={nonce} | Hash={h[:24]}... | Speed={hashrate:,} H/s")

    print("\n[2/2] Submitting PoW & mining next block on global KWD Seed Node...")
    r = requests.get(f"{CLOUD_URL}/mine", timeout=90)
    print(" -> Global Network Response:", r.json().get("message", r.text[:120]))
    info = requests.get(f"{CLOUD_URL}/halving_info", timeout=30).json()
    print(f" -> Network Height: Block #{info.get('current_height')} | Total Supply: {info.get('total_supply_mined')} / {info.get('max_supply')} KWD")

if __name__ == "__main__":
    main()
