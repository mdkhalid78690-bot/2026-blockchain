import json
import os
import subprocess
import time
import requests

CLOUD = "https://two026-blockchain.onrender.com"
INTERVAL_SECONDS = 180  # Check every 3 minutes

print("==================================================")
print("  KWD Auto-Sync Daemon Started")
print("  Watching Render node for new blocks every 3 min")
print("==================================================")

while True:
    try:
        # 1. Fetch remote chain height
        res = requests.get(f"{CLOUD}/chain", timeout=240)
        if res.status_code == 200:
            remote_chain = res.json().get("chain", [])
            remote_height = len(remote_chain)
            
            # Read local chain
            local_height = 0
            if os.path.exists("blockchain_data.json"):
                with open("blockchain_data.json", "r", encoding="utf-8") as f:
                    local_chain = json.load(f)
                    local_height = len(local_chain)
            
            # 2. If new blocks were mined, sync and push to GitHub
            if remote_height > local_height:
                print(f"[{time.strftime('%H:%M:%S')}] Detected new blocks! Cloud: {remote_height} | Local: {local_height}")
                
                with open("blockchain_data.json", "w", encoding="utf-8") as f:
                    json.dump(remote_chain, f, indent=2)
                
                # Try syncing exchange book
                try:
                    ex = requests.get(f"{CLOUD}/api/exchange/book", timeout=30).json()
                    with open("exchange_data.json", "w", encoding="utf-8") as f:
                        json.dump(ex, f, indent=2)
                except Exception:
                    pass
                
                # Run Git commands
                subprocess.run(["git", "add", "blockchain_data.json", "exchange_data.json"], check=True)
                commit_msg = f"[skip render] Auto-sync: Chain advanced to Block {remote_height}"
                subprocess.run(["git", "commit", "-m", commit_msg], check=True)
                subprocess.run(["git", "push", "origin", "main"], check=True)
                print(f"[{time.strftime('%H:%M:%S')}] Successfully pushed Block {remote_height} to GitHub!\n")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] In sync at Block {local_height}. Waiting...")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Node responded with status: {res.status_code}")
    except Exception as err:
        print(f"[{time.strftime('%H:%M:%S')}] Watcher warning: {err}")
    
    time.sleep(INTERVAL_SECONDS)
