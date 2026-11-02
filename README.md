# KawaidCoin (KWD) - Multi-Node Proof-of-Work Blockchain in Python

A Bitcoin-style, 5-node Peer-to-Peer (P2P) Proof-of-Work blockchain built from scratch in Python.

## Key Features
- SHA-256 Proof-of-Work & Auto-Difficulty Retargeting (adjusts every 10 blocks)
- Cryptographic ECDSA Wallets & Signatures (Secp256k1 signing, replay protection, fees)
- Merkle Trees & SPV Proofs (Full block Merkle roots and /merkle_proof/<txid> verification)
- Bitcoin Halving Schedule (21,000,000 KWD max supply cap with /halving_info countdown)
- 5-Node P2P Consensus (Longest/heaviest chain fork resolution, mempool sync, and /faucet/<address>)
- Live Web Block Explorer (/explorer dashboard and /send transaction page)

## Quick Start (Windows PowerShell)
- Start 5-Node Cluster: .\start_network.ps1
- Stop 5-Node Cluster: .\stop_network.ps1
- Run 36 Automated Tests: python api_tests.py
