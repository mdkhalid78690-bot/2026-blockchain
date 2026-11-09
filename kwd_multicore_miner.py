import sys
import time
import json
import hashlib
import multiprocessing as mp
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

        reward = 12.5
        try:
            r = requests.get(f"{node_url}/halving_info", timeout=2)
            if r.status_code == 200:
                reward = float(r.json().get("current_reward", 12.5))
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

def worker_search(worker_id, num_workers, prefix_str, suffix_bytes, target_bytes, stop_event, result_queue, counter):
    proof = worker_id
    base_sha = hashlib.sha256(prefix_str.encode())
    local_count = 0

    while not stop_event.is_set():
        h_obj = base_sha.copy()
        h_obj.update(f"{proof}".encode())
        h_obj.update(suffix_bytes)

        if h_obj.digest() < target_bytes:
            stop_event.set()
            result_queue.put((proof, h_obj.hexdigest()))
            break

        proof += num_workers
        local_count += 1
        if local_count >= 100000:
            with counter.get_lock():
                counter.value += local_count
            local_count = 0

def commit_block(candidate_block, node_url):
    # Try HTTP Node submission
    try:
        res = requests.post(f"{node_url}/receive_block", json=candidate_block, timeout=5)
        print(f"[>] Master Node HTTP Response: {res.status_code} - {res.text}")
        if res.status_code in (200, 201):
            return
    except Exception:
        print("[*] HTTP Node unavailable. Using Bitcoin v0.1 autonomous disk commit...")

    # Autonomous Ledger Fallback
    chain = core.read_json(core.CHAIN_FILE, [])
    tip = chain[-1] if chain else None
    ok, err = core.validate_block(
        candidate_block,
        previous_block=tip,
        full_transactions=True,
        prior_chain=chain,
        check_future_time=False
    )
    if ok:
        chain.append(candidate_block)
        core.write_json(core.CHAIN_FILE, chain)
        print(f"[+] SUCCESS: Committed Block #{candidate_block['index']} directly into ledger!")
    else:
        print(f"[!] Validation rejected: {err}")

def mine_loop(wallet_address, node_url=NODE_URL):
    # Detect CPU cores: leave 1 thread free for system stability and cooling
    total_cores = mp.cpu_count()
    active_workers = max(1, total_cores - 1)

    print("=" * 64)
    print("  KWD Bitcoin v0.2 Multi-Core Parallel Miner")
    print(f"  Target Wallet: {wallet_address}")
    print(f"  CPU Allocation: {active_workers}/{total_cores} threads active")
    print("=" * 64)

    while True:
        work = get_work(node_url)
        if not work or not work["previous_hash"]:
            print("[!] Unable to fetch tip. Retrying in 4 seconds...")
            time.sleep(4)
            continue

        idx = work["height"]
        target_diff = work["difficulty"]
        target = work["target"]
        target_bytes = target.to_bytes(32, "big")
        prev_hash = work["previous_hash"]
        reward_amt = work["reward"]

        print(f"\n[*] Mining Block #{idx} | Difficulty: {target_diff} | Threads: {active_workers}")
        print(f"[*] Target: 0x{target:064x}"[:60] + "...")
        print(f"[*] Previous Hash: {prev_hash[:32]}...")

        block_ts = max(time.time(), float(core.read_json(core.CHAIN_FILE, [{}])[-1].get("timestamp", 0)) + 0.001)
        reward_tx = build_reward_tx(wallet_address, reward_amt, idx, block_ts)

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
        suffix_bytes = suffix_str.encode()

        stop_event = mp.Event()
        result_queue = mp.Queue()
        counter = mp.Value("L", 0)

        processes = []
        for wid in range(active_workers):
            p = mp.Process(
                target=worker_search,
                args=(wid, active_workers, prefix_str, suffix_bytes, target_bytes, stop_event, result_queue, counter)
            )
            p.daemon = True
            p.start()
            processes.append(p)

        start_time = time.time()
        while not stop_event.is_set():
            time.sleep(0.5)
            elapsed = max(0.001, time.time() - start_time)
            total_hashes = counter.value
            hrate = int(total_hashes / elapsed)
            sys.stdout.write(f"\r[*] Parallel Hashrate: {hrate:,} H/s | Total Tested: {total_hashes:,}")
            sys.stdout.flush()

        proof, winning_hash = result_queue.get()
        for p in processes:
            p.join(timeout=0.2)

        elapsed = round(time.time() - start_time, 2)
        print(f"\n[+] SOLVED! Proof: {proof} in {elapsed}s | Hash: {winning_hash[:24]}...")

        candidate_block = {
            "index": idx,
            "timestamp": block_ts,
            "proof": proof,
            "previous_hash": prev_hash,
            "difficulty": target_diff,
            "transactions": [reward_tx],
            "hash": winning_hash
        }

        commit_block(candidate_block, node_url)
        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_multicore_miner.py <YOUR_WALLET_ADDRESS>")
        sys.exit(1)
    mine_loop(sys.argv[1])
