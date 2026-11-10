# 2026 Blockchain Node 1

Version: v0.9.0 Alpha

Status: Local Multi-Node Testnet

License: MIT

A local Python proof-of-work blockchain node for development, testing, and early public testnet experimentation. Node 1 is the primary node in this two-node local network and exposes a full API, explorer UI, wallet management, mining, and peer sync.

## Features

- Proof-of-work block mining with dynamic difficulty
- Transaction validation with nonce replay protection
- Duplicate TXID and double-spend protection
- Mempool management and transaction broadcasting
- Peer discovery, peer registration, and chain sync
- Wallet generation, import, backup, and explorer integration
- Operational health, metrics, and network dashboard endpoints

                Wallet

                   │

                   ▼

         Signed Transaction

                   │

                   ▼

              Flask API

                   │

      ┌────────────┴────────────┐

      ▼                         ▼

   Mempool                Broadcast

      │                         │

      ▼                         ▼

    Mining                Other Nodes

      │

      ▼

 Blockchain Database

      │

      ▼

 Explorer Dashboard

## Folder structure

- `api.py` - Flask node API, explorer routes, and network handling
- `core.py` - blockchain rules, validation, persistence, wallet helpers
- `chain_config.json` - consensus and security configuration
- `node_config.json` - local node identity and port settings
- `blockchain_data.json` - local blockchain history
- `mempool.json` - pending transactions not yet mined
- `peers.json` - known peer addresses
- `public_keys.json` - registered wallet public keys
- `explorer.html` / `send.html` / `block.html` - browser UI pages
- `run_tests.py` / `api_tests.py` / `protocol_tests.py` - built-in test runners

## Requirements

- Python 3.12+
- `Flask`
- `Flask-Cors`
- `requests`
- `ecdsa`

## Installation

```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python -m pip install -r requirements.txt
```

## Run Node 1

```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain"
python api.py
```

Then open the browser at `http://127.0.0.1:5000/explorer`.

## Run Node 2

Node 2 is a mirrored secondary node configured to run on port `5001`.

```powershell
cd "c:\Users\MD khalid\Desktop\2026 blockchain node2"
python api.py
```

Then open `http://127.0.0.1:5001/explorer`.

## Generate wallet

Use the API to create a new wallet:

```bash
curl http://127.0.0.1:5000/generate_wallet
```

Or import an existing private key:

```bash
curl -X POST http://127.0.0.1:5000/import_wallet -H "Content-Type: application/json" -d '{"private_key":"<YOUR_PRIVATE_KEY>"}'
```

## Mine blocks

Mine the next block on Node 1:

```bash
curl http://127.0.0.1:5000/mine
```

Node 2 can also mine if it has a funded address and is synced:

```bash
curl http://127.0.0.1:5001/mine
```

## Send transaction

Create and broadcast a signed transaction from your wallet:

```bash
curl -X POST http://127.0.0.1:5000/send_transaction \
  -H "Content-Type: application/json" \
  -d '{"private_key":"<YOUR_PRIVATE_KEY>","to":"<RECIPIENT_ADDRESS>","amount":1,"fee":0.01}'
```

Alternatively submit a prepared transaction payload to Node 1:

```bash
curl -X POST http://127.0.0.1:5000/create_transaction \
  -H "Content-Type: application/json" \
  -d '{"transaction":{"from":"<SENDER>","to":"<RECIPIENT>","amount":1,"fee":0.01,"nonce":1},"signature":"<SIG_HEX>"}'
```

## Explorer

The browser explorer provides:

- Wallet import and backup
- Clickable block hashes and transaction lookup
- Chain and mempool stats
- Interactive charts for supply, difficulty, and block history
- Network health and peer dashboards

Open:

- Node 1: `http://127.0.0.1:5000/explorer`
- Node 2: `http://127.0.0.1:5001/explorer`

## APIs

Core API endpoints:

- `GET /chain` - Full blockchain history
- `GET /node_info` - Node identity and status
- `GET /balance/<address>` - Wallet balance
- `GET /mempool` - Pending transactions
- `GET /latest_block` - Head block
- `GET /mine` - Mine a new block
- `POST /send_transaction` - Sign + submit a transaction
- `POST /create_transaction` - Submit a signed transaction
- `POST /receive_transaction` - Receive a broadcast transaction
- `POST /receive_block` - Receive a broadcast block
- `GET /sync_chain` - Sync chain with peers
- `GET /sync_peers` - Discover and sync peers
- `POST /register_peer` - Register a new peer
- `GET /healthz` - Health check
- `GET /status` - Node summary
- `GET /charts` - Chart data for UI
- `GET /explorer` - Explorer page

Advanced endpoints:

- `GET /ops_status`
- `GET /metrics`
- `GET /network_health_dashboard`
- `POST /bootstrap`
- `POST /backup_wallet`
- `POST /backup_state`
- `POST /restore_state`

## Screenshots

Open the built-in explorer in your browser to see live UI pages and interactive charts. The `explorer.html` file contains the browser dashboard served by the node.

## Security

- ECDSA digital signatures
- Transaction signature verification
- Replay attack protection
- Duplicate TXID protection
- Double-spend protection
- Dynamic Proof-of-Work difficulty
- Longest-chain consensus
- Peer synchronization

## Future roadmap

- Complete public testnet bootstrap and peer discovery
- Add formal peer authentication and HMAC-signed peer requests
- Harden large-scale mempool and block broadcast performance
- Add GUI wallet import/export and secure key storage
- Add full command-line tooling and packaged installers
- Add multi-node stress testing with 1000+ transactions and 10+ nodes
- Add block explorer persistence and historical analytics

## Tested Environment

Operating System:
- Windows 11

Python:
- Python 3.12+

Nodes Tested:
- Node 1
- Node 2

Network:
- Localhost (127.0.0.1)

Explorer:
- Chrome
- Microsoft Edge