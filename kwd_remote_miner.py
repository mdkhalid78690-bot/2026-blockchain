import sys
import time
import json
import hashlib
import requests
import core

NODE_URL = "http://127.0.0.1:5000"

def canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))

def calculate_hash(block):
    block_copy = dict(block)
    block_copy.pop("hash", None)
    return hashlib.sha256(canonical_json(block_copy).encode()).hexdigest()

def get_work(node_url=NODE_URL):
    try:
        chain = core.read_json(core.CHAIN_FILE, [])
        if not chain:
            return None
        tip = chain[-1]
        next_index = int(tip.get("index", len(chain))) + 1
        prev_hash = tip.get("hash", "")
        difficulty = int(core.calculate_next_difficulty(chain))
        target = (1 << (256 - (difficulty * 4))) - 1

        reward = 50.0
        try:
            r = requests.get(f"{node_url}/halving_info", timeout=2)
            if r.status_code == 200:
                reward = float(r.json().get("current_reward") or r.json().get("block_reward") or 50.0)
        except Exception:
            pass

        return {
            "height": next_index,
            "previous_hash": prev_hash,
            "difficulty": difficulty,
            "target": target,
            "reward": reward
        }
    except Exception as e:
        print(f"[!] get_work error: {e}")
        return None

def build_reward_tx(wallet_address, reward_amount, next_index, timestamp):
    tx_inner = {
        "from": "NETWORK",
        "to": wallet_address,
        "amount": float(reward_amount),
        "fee": 0.0,
        "timestamp": timestamp,
        "nonce": next_index
    }
    tx_inner["txid"] = core.hash_data(core.tx_signing_payload(tx_inner))
    return {
        "signature": core.MINING_REWARD_SIGNATURE,
        "transaction": tx_inner
    }

def commit_block_locally(candidate_block):
    chain = core.read_json(core.CHAIN_FILE, [])
    tip = chain[-1] if chain else None
    ok, err = core.validate_block(
        candidate_block,
        previous_block=tip,
        full_transactions=True,
        prior_chain=chain,
        check_future_time=False
    )
    if not ok:
        return False, err
    chain.append(candidate_block)
    core.write_json(core.CHAIN_FILE, chain)
    return True, f"Committed Block #{candidate_block['index']} directly to {core.CHAIN_FILE}"

def mine_loop(wallet_address, node_url=NODE_URL):
    print("=" * 64)
    print("  KawaidCoin (KWD) - Bitcoin v0.1 Midstate CPU Miner")
    print(f"  Target Wallet: {wallet_address}")
    print(f"  Master Node  : {node_url} (with Autonomous Local Fallback)")
    print("=" * 64)

    while True:
        work = get_work(node_url)
        if not work or not work["previous_hash"]:
            print("[!] Unable to fetch chain tip. Retrying in 5 seconds...")
            time.sleep(5)
            continue

        target_diff = work["difficulty"]
        target = work["target"]
        target_bytes = target.to_bytes(32, "big")
        prev_hash = work["previous_hash"]
        idx = work["height"]
        reward_amt = work["reward"]

        print(f"\n[*] Mining Block #{idx} | Difficulty: {target_diff} | Target: 0x{target:064x}"[:78] + "...")
        print(f"[*] Previous Hash: {prev_hash[:32]}...")

        proof = 0
        start_time = time.time()
        block_ts = max(time.time(), float(core.read_json(core.CHAIN_FILE, [{}])[-1].get("timestamp", 0)) + 0.001)
        reward_tx = build_reward_tx(wallet_address, reward_amt, idx, block_ts)

        # Pre-compute canonical JSON prefix & suffix (Satoshi Midstate Optimization)
        template_block = {
            "index": idx,
            "timestamp": block_ts,
            "proof": "__PROOF_PLACEHOLDER__",
            "previous_hash": prev_hash,
            "difficulty": target_diff,
            "transactions": [reward_tx]
        }
        raw_template = canonical_json(template_block)
        prefix_str, suffix_str = raw_template.split('"__PROOF_PLACEHOLDER__"')
        base_sha = hashlib.sha256(prefix_str.encode())
        suffix_bytes = suffix_str.encode()

        while True:
            h_obj = base_sha.copy()
            h_obj.update(f"{proof}".encode())
            h_obj.update(suffix_bytes)

            if h_obj.digest() < target_bytes:
                h = h_obj.hexdigest()
                candidate_block = {
                    "index": idx,
                    "timestamp": block_ts,
                    "proof": proof,
                    "previous_hash": prev_hash,
                    "difficulty": target_diff,
                    "transactions": [reward_tx],
                    "hash": h
                }
                elapsed = round(time.time() - start_time, 2)
                print(f"\n[+] SOLVED! Proof: {proof} in {elapsed}s | Hash: {h[:24]}...")

                # Try submitting to HTTP Node first; fallback to direct ledger commit if offline
                submitted = False
                try:
                    res = requests.post(f"{node_url}/receive_block", json=candidate_block, timeout=5)
                    print(f"[>] Node Response: HTTP {res.status_code} - {res.text}")
                    if res.status_code in (200, 201):
                        submitted = True
                except Exception:
                    print("[*] HTTP Node offline on port 5000 -> Executing Bitcoin v0.1 Direct Ledger Commit...")

                if not submitted:
                    ok, msg = commit_block_locally(candidate_block)
                    if ok:
                        print(f"[+] SUCCESS: {msg}")
                    else:
                        print(f"[!] Local commit rejected: {msg}")
                break

            proof += 1
            if proof % 1000000 == 0:
                elapsed = max(0.001, time.time() - start_time)
                h_rate = int(proof / elapsed)
                sys.stdout.write(f"\r[*] Tested {proof:,} hashes... ({h_rate:,} H/s)")
                sys.stdout.flush()

        time.sleep(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_remote_miner.py <YOUR_WALLET_ADDRESS>")
        sys.exit(1)
    mine_loop(sys.argv[1])
