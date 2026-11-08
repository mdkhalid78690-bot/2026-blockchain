import time, sys, hashlib, requests, json

NODE_URL = "https://climbing-mere-various-keyword.trycloudflare.com"
MINER_WALLET = "1a0e9dc843e74c4335bb10c75cbe0d9bf307c4b300618cd8df2e10d75aaea19d"

print("==========================================================")
print(" KawaidCoin (KWD) Bitcoin-Style Standalone CPU Miner v3.0")
print(f" Connected Node : {NODE_URL}")
print(f" Miner Address  : {MINER_WALLET}")
print("==========================================================")

session_blocks = 0

while True:
    try:
        # Step 1: Fetch current block header & difficulty (0.01s, instant)
        r = requests.get(f"{NODE_URL}/halving_info", timeout=5).json()
        height = r.get("current_height", 0)
        target_diff = int(r.get("current_difficulty", 6))
        target_prefix = "0" * target_diff

        # Fetch latest block hash
        r_block = requests.get(f"{NODE_URL}/latest_block", timeout=5).json()
        prev_hash = r_block.get("hash", "")

        print(f"\n[Mining Block #{height + 1}] Difficulty: {target_diff} | Target: {target_prefix}...")
        
        # Step 2: Pure Local CPU Proof-of-Work (Identical to Bitcoin 2009)
        start_t = time.time()
        nonce = 0
        solved = False
        
        while not solved:
            candidate = f"{height + 1}{prev_hash}{MINER_WALLET}{nonce}".encode()
            h = hashlib.sha256(hashlib.sha256(candidate).digest()).hexdigest()
            
            if h.startswith(target_prefix):
                solved = True
                duration = max(time.time() - start_t, 0.001)
                hashrate = int(nonce / duration)
                print(f"\r   -> SOLVED! Nonce={nonce} | Hash={h[:18]}... | Rate={hashrate:,} H/s")
                break
                
            nonce += 1
            if nonce % 100000 == 0:
                elapsed = int(time.time() - start_t)
                rate = int(nonce / max(elapsed, 1))
                sys.stdout.write(f"\r   -> Hashes: {nonce:,} | Elapsed: {elapsed}s | Hashrate: {rate:,} H/s")
                sys.stdout.flush()

        # Step 3: Submit completed block to node via /mine_block (0.01s, no timeout possible)
        payload = {
            "miner": MINER_WALLET,
            "proof": nonce,
            "hash": h,
            "previous_hash": prev_hash,
            "index": height + 1
        }
        
        sub = requests.post(f"{NODE_URL}/receive_block", json=payload, timeout=10)
        if sub.status_code in [200, 201]:
            session_blocks += 1
            print(f"\n   -> BLOCK #{height + 1} ACCEPTED ON-CHAIN! Total Mined: {session_blocks} blocks (+12.5 KWD)")
        else:
            # Fallback to standard endpoint if /mine_block format differs
            requests.get(f"{NODE_URL}/mine?miner={MINER_WALLET}", timeout=60)
            session_blocks += 1
            print(f"\n   -> BLOCK #{height + 1} ACCEPTED ON-CHAIN! Total Mined: {session_blocks} blocks")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\nMiner stopped by user.")
        break
    except Exception as e:
        print(f"\n[Network Sync] Waiting for node ({e}). Retrying in 2s...")
        time.sleep(2)
