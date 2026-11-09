import sys, time, hashlib, json, requests

DEFAULT_NODE = "http://127.0.0.1:5000"

def get_target(difficulty):
    return "0" * int(difficulty)

def fetch_work(node_url, address):
    try:
        r = requests.get(f"{node_url}/mining_job?address={address}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[!] Node connection error ({node_url}): {e}")
    return None

def submit_block(node_url, block_data):
    try:
        r = requests.post(f"{node_url}/mine", json=block_data, timeout=10)
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def mine_loop(address, node_url):
    print("=" * 60)
    print("       KAWAIDCOIN (KWD) PROOF-OF-WORK CPU MINER")
    print("=" * 60)
    print(f"Payout Wallet Address : {address}")
    print(f"Connected Seed Node   : {node_url}")
    print("Target Target Epoch   : 60s Block Target | Halving every 2.1M")
    print("=" * 60)

    last_index = -1
    while True:
        work = fetch_work(node_url, address)
        if not work or "index" not in work:
            time.sleep(3)
            continue

        index = work["index"]
        if index != last_index:
            last_index = index
            diff = work["difficulty"]
            target = get_target(diff)
            print(f"
[+] New Mining Work Received: Block #{index} | Target Difficulty: {diff}")

        # Nonce search loop (10,000 hashes per batch to keep responsive)
        raw_header = f"{work['index']}{work['previous_hash']}{work['merkle_root']}{work['timestamp']}{work['difficulty']}"
        start_nonce = int(time.time() * 1000) % 1000000
        found = False

        for n in range(start_nonce, start_nonce + 25000):
            h = hashlib.sha256(f"{raw_header}{n}".encode()).hexdigest()
            if h.startswith(target):
                print(f"[>>>] BLOCK SOLVED! Nonce: {n} -> Hash: {h[:28]}...")
                work["nonce"] = n
                work["hash"] = h
                ok, res = submit_block(node_url, work)
                if ok:
                    print(f"[PASS] Block #{index} accepted by network! 50.0 KWD reward credited.")
                else:
                    print(f"[!] Submission rejected: {res}")
                found = True
                time.sleep(1)
                break

        if not found:
            time.sleep(0.05)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_remote_miner.py <WALLET_ADDRESS> [OPTIONAL_NODE_URL]")
        print("Example: python kwd_remote_miner.py 1a0e9dc843e74c4335bb... http://127.0.0.1:5000")
        sys.exit(1)

    miner_wallet = sys.argv[1].strip()
    target_node = sys.argv[2].strip() if len(sys.argv) >= 3 else DEFAULT_NODE
    mine_loop(miner_wallet, target_node)
