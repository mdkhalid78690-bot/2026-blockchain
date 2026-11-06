import os, json, time, hashlib, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CLOUD_URL = "https://two026-blockchain.onrender.com"
WALLET_FILE = "kwd_miner_wallet.json"

def get_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s

def get_or_create_wallet():
    if os.path.exists(WALLET_FILE):
        return json.load(open(WALLET_FILE, "r", encoding="utf-8"))
    seed = os.urandom(32).hex()
    addr = hashlib.sha256(seed.encode()).hexdigest()[:40]
    w = {"address": addr, "private_key": seed}
    json.dump(w, open(WALLET_FILE, "w", encoding="utf-8"), indent=2)
    print(f"[Wallet] Created new personal wallet in {WALLET_FILE} (Keep this file private!)")
    return w

def sha256d(data_str):
    return hashlib.sha256(hashlib.sha256(data_str.encode("utf-8")).digest()).hexdigest()

def main():
    session = get_session()
    w = get_or_create_wallet()
    addr = w["address"]
    print("============================================================")
    print(" KawaidCoin (KWD) Public Standalone CPU Miner v1.0")
    print(f" Connected Node : {CLOUD_URL}")
    print(f" Miner Address  : {addr}")
    print("============================================================\n")

    print("[1/3] Connecting to global KWD Seed Node...")
    for attempt in range(1, 5):
        try:
            ping = session.get(f"{CLOUD_URL}/node_info", timeout=60).json()
            print(f" -> Connected! Network Height: Block #{ping.get('height')} | Chain Work: {ping.get('chain_work')}")
            break
        except Exception:
            print(f" -> Waking up cloud node (attempt {attempt}/4)...")
            time.sleep(3)

    print("\n[2/3] Running local CPU SHA-256 Proof-of-Work...")
    t0 = time.time()
    nonce = 0
    while True:
        h = sha256d(f"{addr}-{nonce}-{t0}")
        if h.startswith("00") and nonce > 5000:
            break
        nonce += 1
    elapsed = max(0.001, time.time() - t0)
    print(f" -> CPU PoW Complete! Nonce={nonce} | Hash={h[:24]}... | Hashrate={int(nonce / elapsed):,} H/s")

    print(f"\n[3/3] Mining next KWD block for Miner Wallet ({addr[:14]}...)...")
    r = session.get(f"{CLOUD_URL}/mine?miner={addr}", timeout=90)
    print(f" -> Network Status: HTTP {r.status_code} | {r.text[:120].strip()}")
    info = session.get(f"{CLOUD_URL}/halving_info", timeout=30).json()
    print(f" -> Updated Height: Block #{info.get('current_height')} | Supply: {info.get('total_supply_mined')} / {info.get('max_supply')} KWD")

if __name__ == "__main__":
    main()
