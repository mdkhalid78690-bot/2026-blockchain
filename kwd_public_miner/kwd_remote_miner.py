import sys, time, json, hashlib, requests

DEFAULT_NODE = "https://kawaidcoin.xyz"

def get_target(difficulty):
    return "0" * int(difficulty)

def fetch_work(node_url, address):
    try:
        r = requests.get(f"{node_url}/mining_job?address={address}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[!] Node connection error ({node_url}): {e}")
    return None

def submit_block(node_url, block_data):
    try:
        r = requests.post(f"{node_url}/receive_block", json=block_data, timeout=15)
        return r.status_code in (200, 201), r.text
    except Exception as e:
        return False, str(e)

def mine_loop(address, node_url):
    print("=" * 60)
    print("       KAWAIDCOIN (KWD) PROOF-OF-WORK CPU MINER")
    print("=" * 60)
    print(f"Payout Wallet Address : {address}")
    print(f"Connected Seed Node   : {node_url}")
    print("Consensus Policy      : 210M Max Supply | 50 KWD | 2.1M Halving")
    print("=" * 60)

    last_index = -1
    proof = 0
    while True:
        work = fetch_work(node_url, address)
        if not work or "index" not in work:
            time.sleep(3)
            continue

        index = work["index"]
        if index != last_index:
            last_index = index
            proof = 0
            diff = work["difficulty"]
            target = get_target(diff)
            print(f"\n[+] New Mining Work Received: Block #{index} | Target Difficulty: {diff}")

        template = dict(work)
        template.pop("hash", None)
        template["proof"] = "__PROOF_PLACEHOLDER__"
        canonical_template = json.dumps(template, sort_keys=True, separators=(",", ":"))
        prefix_str, suffix_str = canonical_template.split('"__PROOF_PLACEHOLDER__"', 1)
        prefix_bytes = prefix_str.encode()
        suffix_bytes = suffix_str.encode()

        batch_size = 2000000
        t0 = time.time()
        found = False

        for p in range(proof, proof + batch_size):
            h = hashlib.sha256(prefix_bytes + str(p).encode() + suffix_bytes).hexdigest()
            if h.startswith(target):
                print(f"\n[>>>] BLOCK SOLVED! Proof: {p} -> Hash: {h[:28]}...")
                work["proof"] = p
                work["hash"] = h
                ok, res = submit_block(node_url, work)
                if ok:
                    print(f"[PASS] Block #{index} accepted by network! 50.0 KWD reward credited.")
                else:
                    print(f"[!] Submission rejected: {res}")
                found = True
                proof = 0
                time.sleep(1)
                break

        if not found:
            proof += batch_size
            dt = max(time.time() - t0, 0.001)
            rate = int(batch_size / dt)
            print(f"\r[*] Block #{index} | Checked {proof:,} proofs | Speed: {rate:,} H/s   ", end="", flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_remote_miner.py <WALLET_ADDRESS> [OPTIONAL_NODE_URL]")
        sys.exit(1)

    miner_wallet = sys.argv[1].strip()
    target_node = sys.argv[2].strip() if len(sys.argv) >= 3 else DEFAULT_NODE
    mine_loop(miner_wallet, target_node)
