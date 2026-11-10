import time, sys, hashlib, requests

NODE = "http://127.0.0.1:5000"
WALLET = "1a0e9dc843e74c4335bb10c75cbe0d9bf307c4b300618cd8df2e10d75aaea19d"

print("==================================================")
print(" KWD Bitcoin-Style CPU Miner v3.0 (Local Engine)")
print(" Node   : " + NODE)
print(" Wallet : " + WALLET)
print("==================================================")

blocks = 0
while True:
    try:
        info = requests.get(NODE + "/halving_info", timeout=5).json()
        h = info.get("current_height", 0)
        diff = int(info.get("current_difficulty", 6))
        prefix = "0" * diff

        b = requests.get(NODE + "/latest_block", timeout=5).json()
        prev = b.get("hash", "")

        print("\nMining Block #" + str(h + 1) + " | Difficulty: " + str(diff))
        t0 = time.time()
        nonce = 0
        while True:
            raw = str(h + 1) + str(prev) + WALLET + str(nonce)
            sol = hashlib.sha256(hashlib.sha256(raw.encode()).digest()).hexdigest()
            if sol.startswith(prefix):
                sec = max(time.time() - t0, 0.001)
                rate = int(nonce / sec)
                print("\rSOLVED! Nonce=" + str(nonce) + " | Rate=" + str(rate) + " H/s")
                break
            nonce += 1
            if nonce % 100000 == 0:
                sec = max(time.time() - t0, 1)
                sys.stdout.write("\rHashes: " + str(nonce) + " | Rate: " + str(int(nonce/sec)) + " H/s")
                sys.stdout.flush()

        tx = {"miner": WALLET, "proof": nonce, "hash": sol, "previous_hash": prev, "index": h + 1}
        res = requests.post(NODE + "/submit_block", json=tx, timeout=10)
        if res.status_code in [200, 201]:
            blocks += 1
            print("\n-> BLOCK #" + str(h + 1) + " ACCEPTED! (+12.5 KWD) Total: " + str(blocks))
        else:
            print("\nNode response HTTP " + str(res.status_code) + ": " + res.text)
        time.sleep(1)
    except KeyboardInterrupt:
        print("\nMiner stopped by user.")
        break
    except Exception as e:
        print("\nSync wait: " + str(e))
        time.sleep(2)
