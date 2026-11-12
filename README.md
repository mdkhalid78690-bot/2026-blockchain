# KawaidCoin (KWD) Mainnet

KawaidCoin (KWD) is an open-source Proof-of-Work cryptocurrency built on SHA-256 consensus with a Bitcoin-inspired monetary policy and autonomous difficulty retargeting.

## Specifications
- **Ticker:** KWD
- **Consensus:** SHA-256 Proof-of-Work
- **Max Supply:** 210,000,000.00 KWD
- **Initial Block Reward:** 50.0 KWD
- **Halving Interval:** Every 2,100,000 blocks (~4 years at 60s block time)
- **Target Block Time:** 60 seconds
- **Difficulty Retargeting:** Every 1,440 blocks (~24 hours)
- **Cryptography:** SECP256k1 ECDSA signatures

## Official Endpoints & Community
- **Live Block Explorer & Faucet:** https://kawaidcoin.xyz/explorer
- **Official Seed Node:** https://kawaidcoin.xyz (Direct IP: `129.225.86.198:5000`)
- **Web Wallet & Transfer:** https://kawaidcoin.xyz/send
- **1-Click CPU Miner Download:** https://kawaidcoin.xyz/download/miner
- **Discord Community:** https://discord.gg/wmuCrE6bSa
- **Bitcointalk ANN:** https://bitcointalk.org/index.php?topic=5599140.0

## Quick Start for Miners

### 1. Download & Extract
Download `KWD_Public_Miner.zip` from the [official releases](https://github.com/mdkhalid78690-bot/2026-blockchain/releases) or directly from the [Mainnet Portal](https://kawaidcoin.xyz/download/miner), then extract the archive.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Generate Wallet & Mine
- **Windows:** Double-click `start_mining.bat`. It will automatically generate your SECP256k1 wallet (`my_kwd_wallet.json`) if you do not already have one and begin mining to your payout address immediately.
- **Linux / macOS:**
```bash
python generate_wallet.py
python kwd_remote_miner.py <YOUR_WALLET_ADDRESS> https://kawaidcoin.xyz
```

## Running a Full Node
```bash
git clone https://github.com/mdkhalid78690-bot/2026-blockchain.git
cd 2026-blockchain
pip install -r requirements.txt
python api.py
```
