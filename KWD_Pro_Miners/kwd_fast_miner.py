import sys, time, json, hashlib, requests
import multiprocessing as mp

DEFAULT_NODE = "https://kawaidcoin.xyz"

def fetch_work(node_url, address):
    try:
        r = requests.get(f"{node_url}/mining_job?address={address}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"\n[!] Node connection error ({node_url}): {e}")
    return None

def get_tip_height(node_url):
    try:
        r = requests.get(f"{node_url}/node_info", timeout=3)
        if r.status_code == 200:
            return int(r.json().get("height", -1))
    except Exception:
        pass
    return -1

def submit_block(node_url, block_data):
    try:
        r = requests.post(f"{node_url}/receive_block", json=block_data, timeout=15)
        return r.status_code in (200, 201), r.text
    except Exception as e:
        return False, str(e)

def persistent_worker(worker_id, num_workers, job_queue, result_queue, job_id_raw, hash_counts):
    sha256 = hashlib.sha256
    batch_steps = 500000 * num_workers
    while True:
        job = job_queue.get()
        if job is None:
            break
        job_id, prefix_bytes, suffix_bytes, target_prefix = job
        proof = worker_id

        while job_id_raw.value == job_id:
            end_proof = proof + batch_steps
            for p in range(proof, end_proof, num_workers):
                h = sha256(prefix_bytes + str(p).encode() + suffix_bytes).hexdigest()
                if h.startswith(target_prefix):
                    if job_id_raw.value == job_id:
                        job_id_raw.value = -1
                        result_queue.put((job_id, p, h))
                    break
            proof = end_proof
            hash_counts[worker_id] += 500000

def mine_loop(address, node_url, num_workers):
    print("=" * 64)
    print("       KAWAIDCOIN (KWD) LOCK-FREE MULTI-CORE CPU MINER")
    print("=" * 64)
    print(f"Payout Wallet Address : {address}")
    print(f"Connected Seed Node   : {node_url}")
    print(f"Active CPU Workers    : {num_workers} lock-free cores")
    print("=" * 64)

    job_queues = [mp.Queue(maxsize=2) for _ in range(num_workers)]
    result_queue = mp.Queue()
    job_id_raw = mp.RawValue("i", 0)
    hash_counts = mp.RawArray("Q", num_workers)

    workers = []
    for wid in range(num_workers):
        p = mp.Process(
            target=persistent_worker,
            args=(wid, num_workers, job_queues[wid], result_queue, job_id_raw, hash_counts),
            daemon=True
        )
        p.start()
        workers.append(p)

    time.sleep(1.5)
    current_job_id = 0

    try:
        while True:
            work = fetch_work(node_url, address)
            if not work or "index" not in work:
                time.sleep(2)
                continue

            index = int(work["index"])
            diff = int(work["difficulty"])
            target_prefix = "0" * diff

            template = dict(work)
            template.pop("hash", None)
            template["proof"] = "__PROOF_PLACEHOLDER__"
            canonical_template = json.dumps(template, sort_keys=True, separators=(",", ":"))
            prefix_str, suffix_str = canonical_template.split('"__PROOF_PLACEHOLDER__"', 1)
            prefix_bytes = prefix_str.encode()
            suffix_bytes = suffix_str.encode()

            current_job_id += 1
            for i in range(num_workers):
                hash_counts[i] = 0
            job_id_raw.value = current_job_id

            job_payload = (current_job_id, prefix_bytes, suffix_bytes, target_prefix)
            for q in job_queues:
                q.put(job_payload)

            print(f"\n[+] Mining Block #{index} | Difficulty: {diff} | Workers: {num_workers}")
            t0 = time.time()
            last_tip_check = 0.0
            stale = False
            won = None

            while job_id_raw.value == current_job_id:
                time.sleep(0.3)
                now = time.time()

                while not result_queue.empty():
                    jid, proof, winning_hash = result_queue.get_nowait()
                    if jid == current_job_id:
                        won = (proof, winning_hash)
                        break
                if won:
                    break

                if now - last_tip_check >= 1.2:
                    last_tip_check = now
                    tip_h = get_tip_height(node_url)
                    if tip_h >= index:
                        job_id_raw.value = -1
                        stale = True
                        print(f"\n[~] Block #{index} solved by network (tip now #{tip_h}). Switching immediately...")
                        break

                dt = max(now - t0, 0.001)
                tested = sum(hash_counts)
                rate = int(tested / dt)
                print(f"\r[*] Block #{index} | Tested: {tested:,} | Combined Speed: {rate:,} H/s   ", end="", flush=True)

            while not result_queue.empty():
                jid, proof, winning_hash = result_queue.get_nowait()
                if jid == current_job_id and not won:
                    won = (proof, winning_hash)

            if won and not stale:
                proof, winning_hash = won
                dt = max(time.time() - t0, 0.001)
                print(f"\n[>>>] BLOCK #{index} SOLVED in {dt:.2f}s! Proof: {proof} -> Hash: {winning_hash[:28]}...")
                work["proof"] = proof
                work["hash"] = winning_hash
                ok, res = submit_block(node_url, work)
                if ok:
                    print(f"[PASS] Block #{index} ACCEPTED ON-CHAIN! +50.0 KWD credited.")
                else:
                    print(f"[!] Submission rejected: {res}")
    finally:
        job_id_raw.value = -1
        for q in job_queues:
            try:
                q.put_nowait(None)
            except Exception:
                pass

if __name__ == "__main__":
    mp.freeze_support()
    if len(sys.argv) < 2:
        print("Usage: python kwd_fast_miner.py <WALLET_ADDRESS> [NODE_URL] [WORKERS]")
        sys.exit(1)

    miner_wallet = sys.argv[1].strip()
    target_node = sys.argv[2].strip() if len(sys.argv) >= 3 else DEFAULT_NODE
    workers_count = int(sys.argv[3]) if len(sys.argv) >= 4 else max(1, mp.cpu_count() - 1)
    mine_loop(miner_wallet, target_node, workers_count)
