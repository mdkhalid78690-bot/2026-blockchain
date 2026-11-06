import os, json, time, hashlib, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import core

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
    return w

def main():
    session = get_session()
    w = get_or_create_wallet()
    addr = w["address"]
    print("============================================================")
    print(" KawaidCoin (KWD) Public Standalone CPU Miner v1.0")
    print(f" Connected Node : {CLOUD_URL}")
    print(f" Miner Address  : {addr}")
    print("============================================================\n")

    print("[1/3] Syncing ledger with KWD Network...")
    chain = core.read_json("blockchain_data.json", [])
    try:
        r = session.get(f"{CLOUD_URL}/chain", timeout=60).json()
        cloud_chain = r.get("chain", r) if isinstance(r, dict) else r
        if isinstance(cloud_chain, list) and len(cloud_chain) > len(chain):
            chain = cloud_chain
            core.write_json("blockchain_data.json", chain)
    except Exception as e:
        print(f" -> Using local 32-block ledger ({e})")
    print(f" -> Current Ledger Height: Block #{len(chain)}")

    print("\n[2/3] Solving SHA-256 Proof-of-Work on your CPU...")
    prev = chain[-1]
    index = prev["index"] + 1
    diff = int(prev.get("difficulty", 1))
    reward = 50.0 / (2 ** (index // 100))
    ts = time.time()
    coinbase_tx = {
        "signature": "MINING_REWARD",
        "transaction": {
            "amount": reward,
            "base_reward": reward,
            "fees": 0,
            "from": "NETWORK",
            "timestamp": ts,
            "to": addr,
        },
    }
    txs = [coinbase_tx]
    merkle = core.compute_merkle_root(txs) if hasattr(core, "compute_merkle_root") else hashlib.sha256(json.dumps(txs, sort_keys=True).encode()).hexdigest()

    t0 = time.time()
    proof = 0
    prefix = "0" * diff
    while True:
        candidate = {
            "difficulty": diff,
            "index": index,
            "merkle_root": merkle,
            "previous_hash": prev["hash"],
            "proof": proof,
            "timestamp": ts,
            "transactions": txs,
        }
        blk_hash = core.hash_block(candidate) if hasattr(core, "hash_block") else hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        if str(blk_hash).startswith(prefix):
            candidate["hash"] = blk_hash
            break
        proof += 1

    elapsed = max(0.001, time.time() - t0)
    print(f" -> Solved Block #{index}! Nonce={proof} | Hash={blk_hash[:24]}... | Speed={int((proof + 1) / elapsed):,} H/s")
    chain.append(candidate)
    core.write_json("blockchain_data.json", chain)

    print("\n[3/3] Broadcasting solved Block to Cloud Seed Node (/receive_block)...")
    try:
        resp = session.post(f"{CLOUD_URL}/receive_block", json=candidate, timeout=60)
        print(f" -> Cloud Broadcast HTTP {resp.status_code}: {resp.text[:120].strip()}")
    except Exception as e:
        print(f" -> Saved locally for GitHub sync ({e})")

if __name__ == "__main__":
    main()
