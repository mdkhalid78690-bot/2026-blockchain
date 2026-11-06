# KawaidCoin (KWD) - Proof-of-Work Blockchain & P2P Network

KawaidCoin (**KWD**) is an open-source, Bitcoin-architected SHA-256 Proof-of-Work blockchain built in Python with ECDSA cryptographic signatures, Merkle Tree SPV proofs, automatic difficulty retargeting, a 21,000,000 KWD hard supply cap, and a live Peer-to-Peer Orderbook Exchange.

## Live Public Network Links
- **Live Block Explorer, Faucet & SPV Verifier:** https://two026-blockchain.onrender.com/explorer
- **Live Peer-to-Peer KWD Exchange:** https://two026-blockchain.onrender.com/exchange
- **Live Send KWD Portal:** https://two026-blockchain.onrender.com/send
- **Live Halving & Supply API:** https://two026-blockchain.onrender.com/halving_info

## Core Protocol Specifications
- **Consensus:** SHA-256 Proof-of-Work (PoW) with cumulative chain-work selection
- **Maximum Supply:** 21,000,000.0 KWD
- **Block Reward & Halving:** 50.0 KWD initial reward, halving every 100 blocks
- **Cryptography:** SECP256k1 ECDSA public/private key signatures & SHA-256 Merkle Trees

## How to Mine KWD on Your Computer (2-Step Quickstart)
1. Download miner.py from https://two026-blockchain.onrender.com/explorer (click **Download CPU Miner**).
2. Open a terminal in that folder and run: pip install requests && python miner.py
