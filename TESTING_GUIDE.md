# 🧪 Testing Guide: KawaidCoin Testnet Nodes

## **Quick Start: Run Automated Tests**

### Run All Tests (Main Node)
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python api_tests.py
```
Expected output: `"passed": 34, "failed": 0`

### Run All Tests (Mirrored Node 2)
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
python api_tests.py
```
Expected output: `"passed": 34, "failed": 0`

---

## **Manual Testing: Step-by-Step**

### **Step 1: Start Both Nodes**

#### Terminal 1 - Main Node (Port 5000)
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python api.py
```
Wait for: `Running on http://127.0.0.1:5000`

#### Terminal 2 - Node 2 (Port 5001)
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
python api.py
```
Wait for: `Running on http://127.0.0.1:5001`

---

### **Step 2: Test Basic Health Endpoints**

#### Check Main Node Status
```powershell
curl http://127.0.0.1:5000/status
```
Expected: JSON with chain length, peers, mempool info

#### Check Node 2 Status
```powershell
curl http://127.0.0.1:5001/status
```
Expected: JSON with chain length, peers, mempool info

---

### **Step 3: Upgrade 1 - TLS/HTTPS Peer URLs**

#### Check if TLS is enabled
```powershell
curl http://127.0.0.1:5000/deployment_status | ConvertFrom-Json | Select-Object -ExpandProperty security
```
Expected: `"tls_enabled": false` (or true if enabled)

#### Verify HTTPS scheme when TLS enabled
```powershell
# This is tested automatically in api_tests.py
# test_tls_enabled_bootstrap_uses_https_peer_urls
```

---

### **Step 4: Upgrade 2 - External Node Onboarding**

#### Check startup script exists
```powershell
ls "c:\Users\MD khalid\Desktop\2026 blockchain\start_testnet_node.ps1"
ls "c:\Users\MD khalid\Desktop\2026 blockchain node2\start_testnet_node.ps1"
```
Expected: Both files exist

#### View startup script
```powershell
Get-Content "c:\Users\MD khalid\Desktop\2026 blockchain\start_testnet_node.ps1"
```
Look for: `-SeedNodes` parameter

---

### **Step 5: Upgrade 3 - Deployment Controls**

#### Check deployment status
```powershell
curl http://127.0.0.1:5000/deployment_status
```
Expected: JSON with rollout_state

#### Enable public API (requires admin token)
```powershell
$token = "admin-token"  # Set actual token from config if needed
$body = @{
    action = "set"
    key = "public_api_enabled"
    value = $true
} | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/deployment_control `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d $body
```
Expected: `"status": "ok"`

#### Check rollout safety mode
```powershell
curl http://127.0.0.1:5000/deployment_status | ConvertFrom-Json | Select-Object -ExpandProperty rollout_state
```
Expected: rollout_safety_mode status

---

### **Step 6: Upgrade 4 - Monitoring & Observability**

#### Check health endpoint
```powershell
curl http://127.0.0.1:5000/healthz
```
Expected: JSON with healthy_peers count, last_events array

#### Check metrics endpoint
```powershell
curl http://127.0.0.1:5000/metrics
```
Expected: JSON with peer_health list

#### Check operations status
```powershell
curl http://127.0.0.1:5000/ops_status
```
Expected: JSON with network summary and bootstrap_state

---

### **Step 7: Upgrade 5 - Trust-Policy Automation**

#### View current trust policy
```powershell
curl http://127.0.0.1:5000/deployment_status | ConvertFrom-Json | Select-Object -ExpandProperty peer_trust_policy
```
Expected: JSON with allow_public_bootstrap, allowlist, denylist

#### Update trust policy (requires admin token)
```powershell
$token = "admin-token"
$body = @{
    action = "promote_by_reputation"
    threshold = 10
} | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/trust_policy_update `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d $body
```
Expected: `"status": "ok"` with promoted peers list

---

### **Step 8: Upgrade 6 - Launch Checklist & Health Dashboard**

#### Check launch readiness
```powershell
curl http://127.0.0.1:5000/launch_readiness
```
Expected: JSON with:
- `ready_for_launch: true/false`
- `readiness_checks`: Object with all checks (chain_initialized, tls_enabled, etc.)
- `chain_height`: Number ≥ 1
- `healthy_peers_count`: Number

#### View deployment runbook
```powershell
curl http://127.0.0.1:5000/deployment_runbook
```
Expected: JSON with 7 launch steps, each with:
- step number
- title
- description
- endpoint
- command

#### Check network health dashboard
```powershell
curl http://127.0.0.1:5000/network_health_dashboard
```
Expected: Comprehensive JSON with:
- node: {node_id, version, network_id, port}
- blockchain: {height, latest_block_hash, difficulty}
- network: {total_peers, healthy_peers, seed_nodes, blacklisted_peers}
- mempool: {pending_transactions, total_pending_fees}
- security: {tls_enabled, rate_limiting_enabled, public_api_enabled, etc.}
- bootstrap_state: {state, last_bootstrap_time, seed_nodes_count}
- peer_health: [list of peers]

---

## **Testing Network Communication**

### Register Node 2 as Peer to Node 1
```powershell
$body = @{ peer = "127.0.0.1:5001" } | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/register_peer `
  -H "Content-Type: application/json" `
  -d $body
```
Expected: `"message": "Peer registered"` or `"Peer is self, ignored"`

### Sync Peers
```powershell
curl http://127.0.0.1:5000/sync_peers
```
Expected: JSON with peers synced, added count, errors

### Peer Health Check
```powershell
curl http://127.0.0.1:5000/peer_health
```
Expected: Array of peers with online status, reputation score

---

## **Testing Wallet & Transactions**

### Check Wallet Status
```powershell
curl http://127.0.0.1:5000/wallets
```
Expected: List of wallets

### Create Test Transaction
```powershell
$body = @{
    from = "sender_address"
    to = "receiver_address"
    amount = 100
    private_key = "sender_private_key"
} | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/send_transaction `
  -H "Content-Type: application/json" `
  -d $body
```
Expected: Transaction ID or error message

### Check Mempool
```powershell
curl http://127.0.0.1:5000/mempool
```
Expected: Array of pending transactions

---

## **Testing Bootstrap & Node Discovery**

### Bootstrap from Seed Nodes
```powershell
$body = @{
    seed_nodes = @("seed.example.com:443")
} | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/bootstrap `
  -H "Content-Type: application/json" `
  -d $body
```
Expected: Bootstrap initiated, peers discovered

### Check Bootstrap Status
```powershell
curl http://127.0.0.1:5000/deployment_status | ConvertFrom-Json | Select-Object -ExpandProperty security
```
Look for: bootstrap_state information

---

## **Testing Security Features**

### Check Rate Limiting
```powershell
# Make rapid requests to trigger rate limit
for ($i = 0; $i -lt 200; $i++) {
    curl http://127.0.0.1:5000/status
}
```
Expected: After ~120 requests: `HTTP 429 Too Many Requests`

### Check Admin Authentication
```powershell
# Without token (should fail if admin_token is set)
curl -X POST http://127.0.0.1:5000/deployment_control `
  -H "Content-Type: application/json" `
  -d '{"action":"set","key":"rate_limit","value":100}'
```
Expected: `"error": "Admin authentication required"` with status 403

### With Valid Token
```powershell
curl -X POST http://127.0.0.1:5000/deployment_control `
  -H "Authorization: Bearer admin-token" `
  -H "Content-Type: application/json" `
  -d '{"action":"set","key":"rate_limit","value":100}'
```
Expected: `"status": "ok"`

---

## **Testing Blockchain Operations**

### Get Blockchain
```powershell
curl http://127.0.0.1:5000/blockchain
```
Expected: Array of blocks with increasing indices

### Mine Block
```powershell
curl -X POST http://127.0.0.1:5000/mine
```
Expected: New block mined, added to chain

### Get Block by Index
```powershell
curl http://127.0.0.1:5000/block/1
```
Expected: Block JSON with index, timestamp, transactions, hash

### Validate Chain
```powershell
curl http://127.0.0.1:5000/validate_chain
```
Expected: `"valid": true` or error message

---

## **Testing Both Nodes Together (HA Mode)**

### 1. Start both nodes (see Step 1)

### 2. Register Node 2 with Node 1
```powershell
$body = @{ peer = "127.0.0.1:5001" } | ConvertTo-Json
curl -X POST http://127.0.0.1:5000/register_peer `
  -H "Content-Type: application/json" `
  -d $body
```

### 3. Mine block on Node 1
```powershell
curl -X POST http://127.0.0.1:5000/mine
```

### 4. Check if Node 2 synced
```powershell
curl http://127.0.0.1:5001/blockchain | ConvertFrom-Json | Select-Object -ExpandProperty length
```
Expected: Same chain length as Node 1 after sync

### 5. Test network resilience
Kill Node 1, verify Node 2 stays operational:
```powershell
# In terminal with Node 1, press Ctrl+C to stop
# In another terminal:
curl http://127.0.0.1:5001/status
```
Expected: Node 2 still responds

---

## **Checking Configuration Files**

### View Chain Config
```powershell
Get-Content "c:\Users\MD khalid\Desktop\2026 blockchain\chain_config.json" | ConvertFrom-Json
```

### View Node Config
```powershell
Get-Content "c:\Users\MD khalid\Desktop\2026 blockchain\node_config.json" | ConvertFrom-Json
```

### View Peers List
```powershell
Get-Content "c:\Users\MD khalid\Desktop\2026 blockchain\peers.json" | ConvertFrom-Json
```

### View Wallet Data
```powershell
Get-Content "c:\Users\MD khalid\Desktop\2026 blockchain\wallets.json" | ConvertFrom-Json
```

---

## **Testing Results Checklist**

✅ Automated tests: 34/34 passing
✅ Basic health endpoints respond
✅ Upgrade 1: HTTPS peer URLs when TLS enabled
✅ Upgrade 2: Startup scripts available
✅ Upgrade 3: Deployment controls work with auth
✅ Upgrade 4: Health/metrics/ops_status endpoints respond
✅ Upgrade 5: Trust-policy automation endpoints work
✅ Upgrade 6: Launch readiness, runbook, dashboard available
✅ Both nodes communicate and sync
✅ Rate limiting works
✅ Admin authentication enforced
✅ Blockchain validates correctly

---

## **Troubleshooting**

### Port Already in Use
```powershell
# Find process using port 5000
netstat -ano | findstr :5000
# Kill process
taskkill /PID <PID> /F
```

### Import Errors
```powershell
# Reinstall dependencies
pip install flask flask-cors cryptography ecdsa requests
```

### JSON Parse Errors
```powershell
# Format JSON output
curl http://127.0.0.1:5000/status | ConvertFrom-Json | ConvertTo-Json
```

### Configuration Reset
```powershell
# Delete config files and restart (will recreate defaults)
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
rm chain_config.json
python api.py  # Recreates with defaults
```

---

## **Performance Testing**

### Measure Response Time
```powershell
Measure-Command {
    curl http://127.0.0.1:5000/status
} | Select-Object -ExpandProperty TotalMilliseconds
```

### Load Testing (25 concurrent requests)
```powershell
$ips = 1..25
$ips | ForEach-Object -Parallel {
    curl http://127.0.0.1:5000/status
} -ThrottleLimit 25
```

---

## **Next Steps for Production Testnet**

1. ✅ Both nodes running and synced
2. ✅ All upgrade features verified working
3. ✅ Security controls tested (auth, rate limiting)
4. ✅ Bootstrap and peer discovery working
5. ✅ Launch readiness shows ready_for_launch: true
6. Follow `/deployment_runbook` steps for public testnet launch
