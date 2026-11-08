import requests, hashlib, json, time, sys

# --- DEFAULT SEED NODE CONFIGURATION ---
NODE_URL = "https://transactions-mysql-conservative-advancement.trycloudflare.com"

def get_work(node_url):
    try:
        r = requests.get(f"{node_url}/halving_info", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                "height": data.get("current_height", 0) + 1,
                "difficulty": data.get("difficulty", 7),
                "previous_hash": data.get("latest_block_hash", "")
            }
    except Exception as e:
        print(f"[!] Error contacting node: {e}")
    return None

def calculate_hash(block):
    raw = json.dumps(block, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def mine_loop(wallet_address, node_url=NODE_URL):
    print("=" * 60)
    print("  KawaidCoin (KWD) - Decentralized Remote CPU Miner")
    print(f"  Target Wallet: {wallet_address}")
    print(f"  Master Node  : {node_url}")
    print("=" * 60)

    while True:
        work = get_work(node_url)
        if not work:
            print("[!] Unable to fetch work. Retrying in 5 seconds...")
            time.sleep(5)
            continue

        target_diff = work["difficulty"]
        prev_hash = work["previous_hash"]
        idx = work["height"]
        prefix = "0" * target_diff

        print(f"\n[*] Mining Block #{idx} | Difficulty: {target_diff}")
        print(f"[*] Previous Hash: {prev_hash[:16]}...")

        proof = 0
        start_time = time.time()
        reward_tx = {
            "signature": "MINING_REWARD",
            "transaction": {
                "from": "NETWORK",
                "to": wallet_address,
                "amount": 12.5,
                "base_reward": 12.5,
                "fees": 0.0,
                "timestamp": time.time()
            }
        }

        while True:
            candidate_block = {
                "index": idx,
                "timestamp": time.time(),
                "proof": proof,
                "previous_hash": prev_hash,
                "difficulty": target_diff,
                "transactions": [reward_tx]
            }
            h = calculate_hash(candidate_block)
            if h.startswith(prefix):
                candidate_block["hash"] = h
                elapsed = round(time.time() - start_time, 2)
                print(f"[+] SOLVED! Proof: {proof} in {elapsed}s | Hash: {h[:20]}...")
                
                # Submit block to Master Node
                try:
                    res = requests.post(f"{node_url}/receive_block", json=candidate_block, timeout=10)
                    print(f"[>] Node Response: HTTP {res.status_code} - {res.text}")
                except Exception as e:
                    print(f"[!] Failed to submit block: {e}")
                break

            proof += 1
            if proof % 500000 == 0:
                h_rate = int(proof / (time.time() - start_time))
                sys.stdout.write(f"\r[*] Tested {proof} hashes... ({h_rate} H/s)")
                sys.stdout.flush()

        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_remote_miner.py <YOUR_WALLET_ADDRESS>")
        sys.exit(1)
    mine_loop(sys.argv[1])
