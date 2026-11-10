# 🧪 Complete Testing Guide - Step-by-Step

## **Quick Summary**

You now have **3 ways to test** your blockchain nodes:

1. **Automated Tests** (Recommended) - Runs 34 tests automatically
2. **Quick Test** - Tests 10 endpoints on both nodes  
3. **Manual Testing** - Use curl to test specific endpoints

---

## **Method 1: Automated Testing (Best)**

Run the complete test suite that validates all 6 upgrades:

### **Main Node (Port 5000)**
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python api_tests.py
```

### **Node 2 (Port 5001)**
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
python api_tests.py
```

**Expected Output:**
```
PASS test_import_wallet
PASS test_send_transaction_endpoint
... (many more tests)
{
    "passed": 34,
    "failed": 0
}
```

**What it tests:**
- ✅ All 6 upgrades working
- ✅ Both nodes feature-parity
- ✅ Security controls enforced
- ✅ Endpoints responding correctly
- ✅ Configuration and state management

---

## **Method 2: Quick Test (5 minutes)**

Fastest way to check if nodes are online and responsive:

### **PowerShell (Recommended for Windows)**
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
.\quick_test.ps1
```

Or from node2:
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
.\quick_test.ps1
```

**What it checks:**
- Status endpoint
- Health check
- Peer health
- Deployment status
- Launch readiness
- Runbook availability
- Health dashboard
- Operations status
- Blockchain validation
- Chain structure

**Expected Output:**
```
✅ PASS | Basic Status Endpoint
✅ PASS | Health Check Endpoint
✅ PASS | Peer Health Endpoint
... (more endpoints)
✅ ALL TESTS PASSED - Nodes are ready!
```

### **Python**
```powershell
python quick_test.py
```

---

## **Method 3: Manual Testing (Detailed)**

Test specific endpoints one by one to understand what's happening.

### **Step A: Start Both Nodes**

#### Terminal 1 - Main Node
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python api.py
```
Look for: `Running on http://127.0.0.1:5000`

#### Terminal 2 - Node 2
```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
python api.py
```
Look for: `Running on http://127.0.0.1:5001`

---

### **Step B: Test Basic Health**

```powershell
# Main Node Status
curl http://127.0.0.1:5000/status

# Node 2 Status
curl http://127.0.0.1:5001/status
```

**Expected:** JSON response with chain, peers, mempool info

---

### **Step C: Test Launch Readiness**

```powershell
# Main Node
curl http://127.0.0.1:5000/launch_readiness | ConvertFrom-Json | ConvertTo-Json

# Node 2
curl http://127.0.0.1:5001/launch_readiness | ConvertFrom-Json | ConvertTo-Json
```

**Look for:**
- `"ready_for_launch": true` (or false - shows what's missing)
- `"chain_height": 1` (or higher)
- `"readiness_checks"` object showing all checks

**Example output:**
```json
{
  "status": "ok",
  "ready_for_launch": true,
  "readiness_checks": {
    "chain_initialized": true,
    "genesis_block_valid": true,
    "tls_enabled": false,
    "rate_limiting_enabled": true,
    "monitoring_enabled": true,
    "seed_nodes_configured": false,
    "trust_policy_configured": false,
    "healthy_peers_available": false,
    "rollout_safety_disabled": true,
    "public_api_enabled": true
  },
  "chain_height": 1,
  "healthy_peers_count": 0
}
```

---

### **Step D: Test Network Health Dashboard**

```powershell
curl http://127.0.0.1:5000/network_health_dashboard | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

**This shows:**
- Node information (ID, version, port)
- Blockchain status (height, latest hash, difficulty)
- Network status (peers, blacklisted nodes)
- Mempool (pending transactions)
- Security configuration
- Bootstrap state

---

### **Step E: View Deployment Runbook**

```powershell
# See step-by-step launch instructions
curl http://127.0.0.1:5000/deployment_runbook | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

This shows the 7 steps to launch public testnet with exact curl commands.

---

### **Step F: Test Node Communication**

#### Register Node 2 as peer to Node 1:
```powershell
$body = @{ peer = "127.0.0.1:5001" } | ConvertTo-Json

curl -X POST http://127.0.0.1:5000/register_peer `
  -H "Content-Type: application/json" `
  -d $body
```

**Expected:** `"message": "Peer registered"` or `"Peer is self, ignored"`

#### Sync peers:
```powershell
curl http://127.0.0.1:5000/sync_peers
```

#### Check peer health:
```powershell
curl http://127.0.0.1:5000/peer_health
```

---

### **Step G: Test Security Controls**

#### Check deployment status:
```powershell
curl http://127.0.0.1:5000/deployment_status | ConvertFrom-Json | ConvertTo-Json
```

**Look for:** `rollout_state`, `public_api_enabled`, `rollout_safety_mode`

#### Test rate limiting:
```powershell
# Make many rapid requests
for ($i = 0; $i -lt 150; $i++) {
    curl http://127.0.0.1:5000/status | Out-Null
}
```

After ~120 requests, you should get:
```
HTTP 429 Too Many Requests
```

---

## **Testing Checklist**

Use this to verify everything works:

### **Automated Tests**
- [ ] Main node: 34/34 tests passing
- [ ] Node 2: 34/34 tests passing

### **Quick Test**
- [ ] Main node: All endpoints responding
- [ ] Node 2: All endpoints responding

### **Manual Tests**
- [ ] Both nodes start without errors
- [ ] Status endpoints return blockchain data
- [ ] Launch readiness shows ready status
- [ ] Health dashboard aggregates data
- [ ] Nodes register each other as peers
- [ ] Rate limiting triggers after ~120 requests
- [ ] Deployment status shows correct config

### **Network Tests**
- [ ] Node 1 can see Node 2
- [ ] Nodes sync peer lists
- [ ] Nodes maintain separate states
- [ ] Both nodes have identical APIs

### **Security Tests**
- [ ] Admin token required for deployment_control
- [ ] Rate limiting prevents abuse
- [ ] Public API enabled/disabled properly
- [ ] Rollout safety mode blocks operations

---

## **Troubleshooting**

### **Issue: "Connection refused" when testing**
```powershell
# Check if nodes are running
netstat -ano | findstr :5000
netstat -ano | findstr :5001

# If not, start them (see Step A above)
```

### **Issue: "Address already in use"**
```powershell
# Find and kill process using port
$pid = (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue).OwningProcess
taskkill /PID $pid /F
```

### **Issue: Test script not found**
```powershell
# Verify you're in the right directory
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
ls quick_test.ps1  # Should exist
ls api_tests.py    # Should exist
```

### **Issue: Import errors running tests**
```powershell
# Reinstall dependencies
pip install flask flask-cors cryptography ecdsa requests
```

---

## **Understanding Test Results**

### **Automated Tests Output**
```
PASS test_name          ✅ Test passed
❌ FAIL error message   ❌ Test failed - shows reason
{
  "passed": 34,         ✅ All 34 tests completed
  "failed": 0           ✅ No failures
}
```

### **Quick Test Output**
```
✅ PASS | Endpoint Name    ✅ Endpoint working
❌ FAIL | Endpoint Name    ❌ Endpoint not responding
```

### **Manual Curl Output**
```json
{
  "status": "ok",            ✅ Endpoint working
  "data": {...}
}
```

Or error:
```json
{
  "error": "description",    ❌ Something failed
  "details": "..."
}
```

---

## **What Each Upgrade Tests**

When you run the 34 tests, here's what's verified:

| Upgrade | Tests | What's Checked |
|---------|-------|----------------|
| 1 (TLS) | test_tls_enabled_bootstrap_uses_https_peer_urls | HTTPS URLs when TLS enabled |
| 2 (Startup) | test_public_bootstrap_startup_scripts_are_available_on_both_nodes | Startup scripts exist |
| 3 (Controls) | 3 tests | Deployment control endpoints, safety gates, authentication |
| 4 (Monitoring) | 2 tests | Health, metrics, ops_status endpoints |
| 5 (Trust) | 3 tests | Trust policy automation, reputation-based actions |
| 6 (Launch) | 3 tests | Launch readiness, runbook, health dashboard |

---

## **Next Steps After Testing**

Once all tests pass:

1. **Verify node configuration**
   ```powershell
   Get-Content chain_config.json | ConvertFrom-Json | ConvertTo-Json
   ```

2. **Check peer registration**
   ```powershell
   Get-Content peers.json | ConvertFrom-Json
   ```

3. **Review launch readiness**
   ```powershell
   curl http://127.0.0.1:5000/launch_readiness
   ```

4. **Follow deployment runbook**
   ```powershell
   curl http://127.0.0.1:5000/deployment_runbook
   ```

5. **Monitor network health**
   ```powershell
   curl http://127.0.0.1:5000/network_health_dashboard
   ```

---

## **Testing Documentation Files**

You now have these files for reference:

- `TESTING_GUIDE.md` - Detailed manual testing guide (this file)
- `quick_test.ps1` - PowerShell quick test script
- `quick_test.py` - Python quick test script
- `api_tests.py` - Comprehensive automated test suite (34 tests)

**Location:** Both nodes have copies in:
- `c:\Users\MD khalid\Desktop\2026 blockchain\`
- `c:\Users\MD khalid\Desktop\2026 blockchain node2\`

---

## **Pro Tips**

✅ **Always start with automated tests first** - Fastest verification
✅ **Use quick_test.ps1** - Good for daily health checks
✅ **Run manual tests for debugging** - Helps understand API
✅ **Both nodes must pass tests** - Ensures feature parity
✅ **Keep startup scripts in terminals** - Easy to restart if needed

---

## **Questions?**

If tests fail, check:
1. Both nodes are running (Step A)
2. Correct port numbers (5000 and 5001)
3. Configuration files exist and are valid
4. Python and dependencies installed
5. Firewall not blocking localhost ports

Good luck with your testnet! 🚀
