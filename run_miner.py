import subprocess, time, sys

WALLET = "1a0e9dc843e74c4335bb10c75cbe0d9bf307c4b300618cd8df2e10d75aaea19d"

print("==========================================================")
print("  KawaidCoin (KWD) Bitcoin-Style Native CPU Miner")
print("  Target Wallet : " + WALLET)
print("  Mode          : Direct Ledger Proof-of-Work (No HTTP Timeout)")
print("==========================================================")

block_count = 0
while True:
    try:
        block_count += 1
        print(f"\n>>> [Mining Session Block #{block_count}] Starting PoW search...")
        start_time = time.time()
        
        proc = subprocess.run(
            [sys.executable, "mine_block.py", WALLET],
            capture_output=True,
            text=True
        )
        
        elapsed = round(time.time() - start_time, 1)
        print(proc.stdout.strip())
        
        if "Block mined successfully" in proc.stdout:
            print(f">>> [SUCCESS] Block mined in {elapsed}s! (+50.0 KWD)")
        else:
            if proc.stderr:
                print(f">>> [Notice] {proc.stderr.strip()}")
                
        time.sleep(1)
        
    except KeyboardInterrupt:
        print("\nMiner stopped by user.")
        break
    except Exception as e:
        print(f"Error: {e}. Retrying in 2s...")
        time.sleep(2)
