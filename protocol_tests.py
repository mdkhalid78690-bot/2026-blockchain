import hashlib
import json
import tempfile
import time
from pathlib import Path

import core


MINER = "a192baf8d91918c436979a1a387c48e78e819b9c5751f72454bf78a4e7376e06"
RECEIVER = "f3b77af047145df0510e7c382aa9ed859feade5b25c159a8a7dd63d4fa84af13"
WALLET1 = "wallet1.json"


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def mine_proof(previous_hash, difficulty):
    proof = 0
    target = "0" * difficulty
    while True:
        proof_hash = hashlib.sha256(f"{previous_hash}{proof}".encode()).hexdigest()
        if proof_hash.startswith(target):
            return proof
        proof += 1


def make_reward_block(chain):
    reward = core.calculate_reward(len(chain), core.get_total_supply(chain))
    previous = chain[-1]
    block = {
        "index": len(chain) + 1,
        "timestamp": max(time.time(), float(previous["timestamp"])),
        "transactions": [{
            "transaction": {
                "from": core.NETWORK,
                "to": MINER,
                "amount": reward,
                "base_reward": reward,
                "fees": 0,
                "timestamp": time.time(),
            },
            "signature": core.MINING_REWARD_SIGNATURE,
        }],
        "proof": 0,
        "difficulty": core.calculate_next_difficulty(chain),
        "previous_hash": previous["hash"],
    }
    block["proof"] = mine_proof(block["previous_hash"], block["difficulty"])
    block["hash"] = core.hash_block(block)
    return block


def make_block(chain, transactions):
    reward = core.calculate_reward(len(chain), core.get_total_supply(chain))
    fees = core.get_pending_fee_total(transactions)
    previous = chain[-1]
    block_txs = list(transactions)
    block_txs.append({
        "transaction": {
            "from": core.NETWORK,
            "to": MINER,
            "amount": reward + fees,
            "base_reward": reward,
            "fees": fees,
            "timestamp": time.time(),
        },
        "signature": core.MINING_REWARD_SIGNATURE,
    })
    block = {
        "index": len(chain) + 1,
        "timestamp": max(time.time(), float(previous["timestamp"])),
        "transactions": block_txs,
        "proof": 0,
        "difficulty": core.calculate_next_difficulty(chain),
        "previous_hash": previous["hash"],
    }
    block["proof"] = mine_proof(block["previous_hash"], block["difficulty"])
    block["hash"] = core.hash_block(block)
    return block


def load_private_key():
    with open(WALLET1, "r") as f:
        return json.load(f)["private_key"]


def fresh_chain():
    return [core.create_genesis_block()]


def test_reward_block_validates():
    chain = fresh_chain()
    block = make_reward_block(chain)
    candidate = chain + [block]
    valid, error = core.validate_chain(candidate)
    assert_true(valid, f"Reward block should validate: {error}")


def test_signed_transaction_and_nonce_replay():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key = load_private_key()
    tx = core.create_signed_transaction(
        private_key,
        RECEIVER,
        10,
        fee=1,
        chain=chain,
        mempool=[],
    )
    valid, error = core.validate_transaction(tx, chain, [])
    assert_true(valid, f"Fresh nonce transaction should validate: {error}")
    block = make_block(chain, [tx])
    chain.append(block)
    valid, error = core.validate_chain(chain)
    assert_true(valid, f"Chain with transaction should validate: {error}")
    valid, error = core.validate_transaction(tx, chain, [])
    assert_true(not valid and "Invalid nonce" in error, "Replay should be rejected by nonce")


def test_replay_attack_is_rejected_for_same_sender_nonce():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key = load_private_key()
    tx = core.create_signed_transaction(
        private_key,
        RECEIVER,
        10,
        fee=1,
        chain=chain,
        mempool=[],
    )
    replay_error = core.replay_attack_error(tx, chain, [tx])
    assert_true(replay_error and "Invalid nonce" in replay_error, "Replay should be blocked explicitly")

    chain_with_tx = chain + [make_block(chain, [tx])]
    replay_error = core.replay_attack_error(tx, chain_with_tx, [])
    assert_true(replay_error and "Invalid nonce" in replay_error, "Replay should be blocked when a matching nonce appears in chain")


def test_double_spend_is_rejected_for_conflicting_pending_transactions():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key, wallet = core.wallet_from_private_key(load_private_key())
    balance = core.get_balance(wallet["address"], chain)
    tx1 = core.create_signed_transaction(
        private_key.to_string().hex(),
        RECEIVER,
        float(balance / 2),
        fee=1,
        chain=chain,
        mempool=[],
    )
    tx2 = core.create_signed_transaction(
        private_key.to_string().hex(),
        RECEIVER,
        float(balance / 2),
        fee=1,
        chain=chain,
        mempool=[tx1],
    )
    valid, error = core.validate_transaction(tx2, chain, [tx1])
    assert_true(not valid and "double spend" in error.lower(), "Conflicting pending spends must be rejected as double spend")


def test_bad_reward_rejected():
    chain = fresh_chain()
    block = make_reward_block(chain)
    reward_tx = block["transactions"][0]["transaction"]
    reward_tx["amount"] += 999
    block["hash"] = core.hash_block(block)
    valid, error = core.validate_chain(chain + [block])
    assert_true(not valid and "Reward amount" in error, "Bad reward must be rejected")


def test_future_timestamp_rejected():
    chain = fresh_chain()
    block = make_reward_block(chain)
    block["timestamp"] = time.time() + core.MAX_FUTURE_BLOCK_TIME + 1000
    block["hash"] = core.hash_block(block)
    valid, error = core.validate_candidate_block(block, check_future_time=True)
    assert_true(not valid and "future" in error, "Future block must be rejected")


def test_duplicate_txid_rejected_in_chain_and_mempool():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key = load_private_key()
    tx = core.create_signed_transaction(
        private_key,
        RECEIVER,
        10,
        fee=1,
        chain=chain,
        mempool=[],
    )
    valid, error = core.validate_transaction(tx, chain, [])
    assert_true(valid, f"Fresh tx should validate: {error}")

    duplicate_in_mempool = core.transaction_duplicate_error(tx, None, [tx])
    assert_true(duplicate_in_mempool and "mempool" in duplicate_in_mempool.lower(), "Duplicate txid in mempool should be rejected")

    chain_with_tx = chain + [make_block(chain, [tx])]
    duplicate_in_chain = core.transaction_duplicate_error(tx, chain_with_tx, [])
    assert_true(duplicate_in_chain and "chain" in duplicate_in_chain.lower(), "Duplicate txid in chain should be rejected")


def test_candidate_block_rejects_wrong_dynamic_difficulty():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    bad_block = make_reward_block(chain)
    bad_block["difficulty"] = core.calculate_next_difficulty(chain) + 1
    bad_block["proof"] = mine_proof(bad_block["previous_hash"], bad_block["difficulty"])
    bad_block["hash"] = core.hash_block(bad_block)
    valid, error = core.validate_candidate_block(
        bad_block,
        check_future_time=False,
        prior_chain=chain,
    )
    assert_true(not valid and "expected" in error.lower(), "Wrong dynamic difficulty must be rejected")


def test_bad_signature_rejected():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key = load_private_key()
    tx = core.create_signed_transaction(
        private_key,
        RECEIVER,
        10,
        fee=1,
        chain=chain,
        mempool=[],
    )
    tx["signature"] = "00" * 64
    valid, error = core.validate_transaction(tx, chain, [])
    assert_true(not valid and "signature" in error.lower(), "Bad signature must be rejected")


def test_duplicate_txid_rejected():
    chain = fresh_chain()
    chain.append(make_reward_block(chain))
    private_key = load_private_key()
    tx = core.create_signed_transaction(
        private_key,
        RECEIVER,
        10,
        fee=1,
        chain=chain,
        mempool=[],
    )
    block = make_block(chain, [tx, tx])
    valid, error = core.validate_chain(chain + [block])
    assert_true(not valid and "duplicate" in error.lower(), "Duplicate txid must be rejected")


def test_chain_work_prefers_harder_chain():
    chain_a = fresh_chain()
    chain_a.append(make_reward_block(chain_a))
    chain_b = fresh_chain()
    harder = make_reward_block(chain_b)
    harder["difficulty"] = 2
    harder["proof"] = mine_proof(harder["previous_hash"], harder["difficulty"])
    harder["hash"] = core.hash_block(harder)
    chain_b.append(harder)
    assert_true(core.chain_work(chain_b) > core.chain_work(chain_a), "Harder chain should score more work")


def test_fork_resolution_prefers_stronger_valid_chain():
    chain_a = fresh_chain()
    chain_a.append(make_reward_block(chain_a))
    chain_b = fresh_chain()
    chain_b.append(make_reward_block(chain_b))
    stronger = make_reward_block(chain_b)
    stronger["difficulty"] = 2
    stronger["proof"] = mine_proof(stronger["previous_hash"], stronger["difficulty"])
    stronger["hash"] = core.hash_block(stronger)
    chain_b.append(stronger)
    assert_true(core.chain_work(chain_b) > core.chain_work(chain_a), "Fork resolution should prefer the stronger chain")


def run():
    core.ensure_chain_config()
    tests = [
        test_reward_block_validates,
        test_signed_transaction_and_nonce_replay,
        test_bad_reward_rejected,
        test_future_timestamp_rejected,
        test_duplicate_txid_rejected_in_chain_and_mempool,
        test_candidate_block_rejects_wrong_dynamic_difficulty,
        test_bad_signature_rejected,
        test_double_spend_is_rejected_for_conflicting_pending_transactions,
        test_duplicate_txid_rejected,
        test_chain_work_prefers_harder_chain,
        test_fork_resolution_prefers_stronger_valid_chain,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(json.dumps({"passed": passed, "failed": 0}, indent=4))


if __name__ == "__main__":
    run()
