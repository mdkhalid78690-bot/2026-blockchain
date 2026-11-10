import sys, time, hashlib, json, requests

DEFAULT_NODE = "http://10.51.134.36:5000"

def canonical_hash_block(block):
    block_copy = {k: v for k, v in block.items() if k != "hash"}
    raw = json.dumps(block_copy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()

def get_target(difficulty):
    return "0" * int(difficulty)

def fetch_work(node_url, address):
    try:
        r = requests.get(f"{node_url}/mining_job?address={address}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[!] Node connection error: {e}")
    return None

def submit_block(node_url, block_data):
    try:
        r = requests.post(f"{node_url}/receive_block", json=block_data, timeout=10)
        return r.status_code in (200, 201), r.text
    except Exception as e:
        return False, str(e)

def mine_loop(address, node_url):
    print("=" * 65)
    print("       KAWAIDCOIN (KWD) LIGHTWEIGHT REMOTE MINER")
    print("=" * 65)
    print(f"Payout Wallet Address : {address}")
    print(f"Connected Seed Node   : {node_url}")
    print("=" * 65)

    last_index = -1
    proof = 0
    work = None
    last_poll_time = 0

    while True:
        now = time.time()
        if work is None or (now - last_poll_time > 10):
            new_work = fetch_work(node_url, address)
            last_poll_time = now
            if new_work and "index" in new_work:
                if work is None or new_work["index"] != last_index:
                    work = new_work
                    last_index = work["index"]
                    diff = work["difficulty"]
                    target = get_target(diff)
                    proof = 0
                    print(f"\n[+] New Template: Block #{last_index} | Target Difficulty: {diff} (0x{'0'*diff}...)")
            else:
                if work is None:
                    time.sleep(2)
                    continue

        prev_hash = work["previous_hash"]
        merkle_root = work["merkle_root"]
        target = get_target(work["difficulty"])

        batch_start = time.time()
        batch_size = 500000
        solved = False

        for _ in range(batch_size):
            h = hashlib.sha256(f"{prev_hash}{merkle_root}{proof}".encode()).hexdigest()
            if h.startswith(target):
                print(f"\n>>> [SOLVED] Block #{last_index}! Proof: {proof} -> PoW Hash: {h[:24]}...")
                work["proof"] = proof
                work["hash"] = canonical_hash_block(work)
                print(f"[+] Canonical Block Hash: {work['hash'][:24]}...")
                
                ok, res = submit_block(node_url, work)
                if ok:
                    print(f"[PASS] Block #{last_index} accepted by network! 50.0 KWD reward credited.\n")
                else:
                    print(f"[!] Submission notice: {res}\n")
                solved = True
                work = None
                time.sleep(2)
                break
            proof += 1

        if not solved:
            elapsed = max(time.time() - batch_start, 0.001)
            hashrate = int(batch_size / elapsed)
            print(f"[*] Mining Block #{last_index}... Nonce: {proof:>10} | Hashrate: {hashrate:,} H/s", end="\r")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_remote_miner.py <WALLET_ADDRESS> [OPTIONAL_NODE_URL]")
        sys.exit(1)
    miner_wallet = sys.argv[1].strip()
    target_node = sys.argv[2].strip() if len(sys.argv) >= 3 else DEFAULT_NODE
    mine_loop(miner_wallet, target_node)
