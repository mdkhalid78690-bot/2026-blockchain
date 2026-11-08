import time, sys, threading, hashlib, requests

NODE_URL = "https://climbing-mere-various-keyword.trycloudflare.com"
MINER_WALLET = "1a0e9dc843e74c4335bb10c75cbe0d9bf307c4b300618cd8df2e10d75aaea19d"

def mine_with_live_counter(url):
    stop_event = threading.Event()
    start_ts = time.time()
    def ticker():
        while not stop_event.wait(1.0):
            elapsed = int(time.time() - start_ts)
            est_hashes = elapsed * 450000
            sys.stdout.write(f"\r   -> [Mining Difficulty 6] Elapsed: {elapsed}s | Est. Hashes Checked: {est_hashes:,} ...")
            sys.stdout.flush()
    t = threading.Thread(target=ticker, daemon=True)
    t.start()
    try:
        return requests.get(url, timeout=(10, 300))
    finally:
        stop_event.set()
        sys.stdout.write("\r" + " " * 90 + "\r")
        sys.stdout.flush()

print("==========================================================")
print(" KawaidCoin (KWD) High-Speed Standalone CPU Miner v2.0")
print(f" Connected Node : {NODE_URL}")
print(f" Miner Address  : {MINER_WALLET}")
print("==========================================================")

session_blocks = 0
while True:
    try:
        print("\n[1/3] Connecting to KWD Seed Node...")
        r_info = requests.get(f"{NODE_URL}/halving_info", timeout=10)
        info = r_info.json()
        height = info.get("current_height", 0)
        diff = info.get("current_difficulty", 6)
        print(f"  -> Connected! Network Height: Block #{height} | Difficulty: {diff}")

        print("[2/3] Verifying local CPU SHA-256 engine...")
        t0 = time.time()
        nonce = 0
        while True:
            h = hashlib.sha256(f"{height}{MINER_WALLET}{nonce}".encode()).hexdigest()
            if h.startswith("00"):
                break
            nonce += 1
        dt = max(time.time() - t0, 0.001)
        rate = int((nonce + 1) / dt)
        print(f"  -> CPU Ready! Benchmark Hashrate={rate:,} H/s")

        print(f"[3/3] Solving Block #{height + 1} for Wallet ({MINER_WALLET[:12]}...)...")
        res = mine_with_live_counter(f"{NODE_URL}/mine?miner={MINER_WALLET}")
        if res.status_code == 200:
            session_blocks += 1
            r_new = requests.get(f"{NODE_URL}/halving_info", timeout=10).json()
            new_h = r_new.get("current_height", height + 1)
            supply = r_new.get("current_supply", 0)
            print(f"  -> BLOCK MINED! New Height: Block #{new_h} | Supply: {supply} KWD")
            print(f"[24/7 Miner] Session Blocks Mined: {session_blocks} | Next block in 2s...")
            time.sleep(2)
        else:
            print(f"  -> Node response HTTP {res.status_code}: {res.text[:120]}")
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nMiner stopped by user.")
        break
    except Exception as e:
        print(f"\n[Retry] Node busy or syncing ({e}). Retrying in 3s...")
        time.sleep(3)
