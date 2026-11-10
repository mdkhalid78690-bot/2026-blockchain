import hashlib
import json
import time
import os

from core import (
    CHAIN_FILE,
    MEMPOOL_FILE,
    MINING_REWARD_SIGNATURE,
    NETWORK,
    calculate_reward,
    calculate_next_difficulty,
    compute_merkle_root,
    get_pending_fee_total,
    get_total_supply,
    hash_block,
    read_json,
    save_mempool,
    tx_id,
    validate_chain,
    validate_transaction,
    write_json,
)


def get_miner_address():
    configured = os.environ.get("KWD_MINER_ADDRESS")
    if configured:
        return configured
    wallet = read_json("wallet1.json", {})
    if wallet.get("address"):
        return wallet["address"]
    wallets = read_json("wallets.json", [])
    for item in wallets:
        if item.get("address") or item.get("wallet"):
            return item.get("address") or item.get("wallet")
    raise RuntimeError("No miner address found. Create a wallet first.")


def mine_proof(previous_hash, difficulty, merkle_root=""):
    proof = 0
    target = "0" * difficulty
    while True:
        proof_hash = hashlib.sha256(f"{previous_hash}{merkle_root}{proof}".encode()).hexdigest()
        if proof_hash.startswith(target):
            return proof
        proof += 1


def main():
    chain = read_json(CHAIN_FILE, [])
    valid, error = validate_chain(chain)
    if not valid:
        raise RuntimeError(f"Cannot mine on invalid chain: {error}")

    mempool = read_json(MEMPOOL_FILE, [])
    accepted_transactions = []
    rejected_transactions = []

    for tx_data in mempool:
        valid, error = validate_transaction(tx_data, chain, accepted_transactions)
        if valid:
            accepted_transactions.append(tx_data)
        else:
            rejected_transactions.append({"txid": tx_id(tx_data), "error": error})

    miner_address = get_miner_address()
    current_height = len(chain)
    reward = calculate_reward(current_height, get_total_supply(chain))
    fee_total = get_pending_fee_total(accepted_transactions)

    if reward > 0 or fee_total > 0:
        accepted_transactions.append({
            "transaction": {
                "from": NETWORK,
                "to": miner_address,
                "amount": reward + fee_total,
                "base_reward": reward,
                "fees": fee_total,
                "timestamp": time.time(),
            },
            "signature": MINING_REWARD_SIGNATURE,
        })

    previous_hash = chain[-1]["hash"]
    difficulty = calculate_next_difficulty(chain)
    merkle_root = compute_merkle_root(accepted_transactions)
    proof = mine_proof(previous_hash, difficulty, merkle_root)
    new_block = {
        "index": len(chain) + 1,
        "timestamp": time.time(),
        "transactions": accepted_transactions,
        "merkle_root": merkle_root,
        "proof": proof,
        "difficulty": difficulty,
        "previous_hash": previous_hash,
    }
    new_block["hash"] = hash_block(new_block)

    chain.append(new_block)
    write_json(CHAIN_FILE, chain)

    accepted_txids = {tx_id(tx) for tx in accepted_transactions}
    remaining_mempool = [tx for tx in mempool if tx_id(tx) not in accepted_txids]
    save_mempool(remaining_mempool, reason="mine_block: mined block cleanup")

    print(json.dumps({
        "message": "Block mined successfully",
        "index": new_block["index"],
        "hash": new_block["hash"],
        "merkle_root": merkle_root,
        "difficulty": difficulty,
        "transactions": len(accepted_transactions),
        "rejected_transactions": rejected_transactions,
    }, indent=4))


if __name__ == "__main__":
    main()
