import base64
import hashlib
import json
import os
import shutil
import sqlite3
import time
from decimal import Decimal
from cryptography.fernet import Fernet

from ecdsa import SECP256k1, SigningKey, VerifyingKey


CHAIN_FILE = "blockchain_data.json"
MEMPOOL_FILE = "mempool.json"
ORPHAN_BLOCKS_FILE = "orphan_blocks.json"
PEERS_FILE = "peers.json"
PUBLIC_KEYS_FILE = "public_keys.json"
WALLETS_FILE = "wallets.json"
WALLET_SECRETS_FILE = "wallet_secrets.json"
BLACKLIST_FILE = "blacklisted_peers.json"
PEER_FAILURES_FILE = "peer_failures.json"
PEER_REPUTATION_FILE = "peer_reputations.json"
PEER_BLACKLIST_DURATION = 600
MAX_PEER_FAILURES = 3
CHAIN_CONFIG_FILE = "chain_config.json"
DB_PATH = "blockchain_state.sqlite3"
NETWORK = "NETWORK"
MINING_REWARD_SIGNATURE = "MINING_REWARD"
MAX_SUPPLY = Decimal("21000000")
MIN_REWARD = Decimal("0.1")
DEFAULT_FEE = Decimal("1")
TARGET_BLOCK_TIME = 60
DIFFICULTY_ADJUSTMENT_INTERVAL = 10
MAX_FUTURE_BLOCK_TIME = 120
MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 8
DEFAULT_CHAIN_CONFIG = {
    "security": {
        "encrypt_private_keys": True,
        "rate_limit": 120,
        "rate_limit_window_seconds": 60,
        "rate_limit_ban_seconds": 60,
        "tls_enabled": False,
        "tls_cert_path": "cert.pem",
        "tls_key_path": "key.pem",
        "peer_shared_secret": None,
        "monitoring_enabled": True,
    },
    "network_name": "KawaidCoin Testnet",
    "ticker": "KWD",
    "network_id": "kwd-testnet-local",
    "genesis_message": "KWD local testnet genesis",
    "genesis_timestamp": 1782300000.0,
    "max_supply": 21000000,
    "initial_reward": 50,
    "min_reward": 0.1,
    "default_fee": 1,
    "target_block_time": 60,
    "difficulty_adjustment_interval": 10,
    "max_future_block_time": 120,
    "min_difficulty": 1,
    "max_difficulty": 8,
    "reward_schedule": [
        {"height": 100, "reward": 25},
        {"height": 200, "reward": 12.5},
        {"height": 840000, "reward": 6.25},
        {"height": 400, "reward": 3.125},
        {"height": 500, "reward": 1.5625},
        {"height": 600, "reward": 0.78125}
    ],
    "peer_registration_token": None,
    "seed_nodes": ["127.0.0.1:5000", "127.0.0.1:5001"]
}


def _storage_key(path):
    return os.path.abspath(path)


def _get_storage_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)"
    )
    return conn


def _read_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def _write_db_value(path, data, updated_at=None):
    payload = json.dumps(data, sort_keys=True)
    key = _storage_key(path)
    conn = _get_storage_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO kv_store(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, payload, updated_at if updated_at is not None else time.time()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_json(path, default):
    key = _storage_key(path)
    conn = _get_storage_connection()
    row = None
    try:
        row = conn.execute(
            "SELECT value, updated_at FROM kv_store WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()

    if os.path.exists(path):
        file_mtime = os.path.getmtime(path)
        if row is None or file_mtime >= (row[1] or 0):
            data = _read_json_file(path, default)
            if data is not default:
                _write_db_value(path, data, updated_at=file_mtime)
            return data

    if row is not None:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default
    return _read_json_file(path, default)


def write_json(path, data):
    _write_db_value(path, data)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)
        os.replace(temp_path, path)
    except OSError:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        try:
            directory = os.path.dirname(os.path.abspath(path)) or "."
            os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4)
        except OSError:
            raise


def save_mempool(mempool_data, reason=None):
    write_json(MEMPOOL_FILE, mempool_data)
    if reason:
        print(f"[save_mempool] saved {len(mempool_data)} pending txs reason={reason}")
    else:
        print(f"[save_mempool] saved {len(mempool_data)} pending txs")


def load_chain_config():
    config = dict(DEFAULT_CHAIN_CONFIG)
    saved = read_json(CHAIN_CONFIG_FILE, {})
    if isinstance(saved, dict):
        config.update(saved)
    return config


def ensure_chain_config():
    if not os.path.exists(CHAIN_CONFIG_FILE):
        write_json(CHAIN_CONFIG_FILE, DEFAULT_CHAIN_CONFIG)
    return load_chain_config()


def get_storage_key_material():
    secret_path = "node_secret.key"
    if not os.path.exists(secret_path):
        key = Fernet.generate_key()
        with open(secret_path, "wb") as handle:
            handle.write(key)
    else:
        with open(secret_path, "rb") as handle:
            key = handle.read()
    return key


def encrypt_secret(value):
    if not value:
        return None
    fernet = Fernet(get_storage_key_material())
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(payload):
    if not payload:
        return None
    fernet = Fernet(get_storage_key_material())
    return fernet.decrypt(payload.encode("utf-8")).decode("utf-8")


def store_wallet_secret(address, private_key):
    secrets = read_json(WALLET_SECRETS_FILE, {})
    secrets[address] = encrypt_secret(private_key)
    write_json(WALLET_SECRETS_FILE, secrets)
    return secrets


def load_wallet_secret(address):
    secrets = read_json(WALLET_SECRETS_FILE, {})
    payload = secrets.get(address)
    if not payload:
        return None
    return decrypt_secret(payload)


def config_decimal(name):
    return Decimal(str(load_chain_config()[name]))


def config_int(name):
    return int(load_chain_config()[name])


def canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def hash_data(data):
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def compute_merkle_root(transactions):
    if not transactions:
        return "0" * 64
    level = [tx_id(tx) or ("0" * 64) for tx in transactions]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level = []
        for i in range(0, len(level), 2):
            combined = f"{level[i]}{level[i + 1]}".encode("utf-8")
            next_level.append(hashlib.sha256(hashlib.sha256(combined).digest()).hexdigest())
        level = next_level
    return level[0]


def compute_merkle_root(transactions):
    if not transactions:
        return "0" * 64
    level = [tx_id(tx) or ("0" * 64) for tx in transactions]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level = []
        for i in range(0, len(level), 2):
            combined = f"{level[i]}{level[i + 1]}".encode("utf-8")
            next_level.append(hashlib.sha256(hashlib.sha256(combined).digest()).hexdigest())
        level = next_level
    return level[0]


def hash_block(block):
    block_copy = dict(block)
    block_copy.pop("hash", None)
    return hash_data(block_copy)


def normalize_peer(peer):
    peer = str(peer).strip().rstrip("/")
    if not peer:
        return None

    if peer.startswith("http://") or peer.startswith("https://"):
        scheme, rest = peer.split("://", 1)
        if rest.startswith("0.0.0.0:"):
            rest = rest.replace("0.0.0.0:", "127.0.0.1:", 1)
        return f"{scheme}://{rest}"

    security_config = load_chain_config().get("security", {})
    scheme = "https" if security_config.get("tls_enabled", False) else "http"
    if peer.startswith("0.0.0.0:"):
        peer = peer.replace("0.0.0.0:", "127.0.0.1:", 1)
    return f"{scheme}://{peer}"


def tx_payload(tx_data):
    if isinstance(tx_data, dict) and "transaction" in tx_data:
        return tx_data["transaction"]
    return tx_data


def tx_signature(tx_data):
    if isinstance(tx_data, dict):
        return tx_data.get("signature")
    return None


def tx_id(tx_data):
    tx = tx_payload(tx_data)
    if not isinstance(tx, dict):
        return None
    if tx.get("txid"):
        return tx["txid"]
    return hash_data(tx_signing_payload(tx))


def tx_signing_payload(tx):
    payload = dict(tx)
    payload.pop("txid", None)
    return payload


def tx_fee(tx):
    try:
        fee = Decimal(str(tx.get("fee", 0)))
    except Exception:
        return None
    if fee < 0:
        return None
    return fee


def tx_spend_amount(tx):
    amount = transaction_amount(tx)
    fee = tx_fee(tx)
    if amount is None or fee is None:
        return None
    return amount + fee


def tx_nonce(tx):
    try:
        nonce = int(tx.get("nonce", 0))
    except Exception:
        return None
    if nonce <= 0:
        return None
    return nonce


def iter_transactions(chain):
    for block in chain:
        for tx_data in block.get("transactions", []):
            yield block, tx_data, tx_payload(tx_data)


def transaction_amount(tx):
    try:
        amount = Decimal(str(tx.get("amount", 0)))
    except Exception:
        return None
    if amount <= 0:
        return None
    return amount


def build_balances(chain):
    balances = {}
    for _block, _tx_data, tx in iter_transactions(chain):
        if not isinstance(tx, dict):
            continue
        sender = tx.get("from")
        receiver = tx.get("to")
        amount = transaction_amount(tx)
        spend = tx_spend_amount(tx)
        if not sender or not receiver or amount is None or spend is None:
            continue
        balances[sender] = balances.get(sender, Decimal("0")) - spend
        balances[receiver] = balances.get(receiver, Decimal("0")) + amount
    return balances


def build_nonces(chain):
    nonces = {}
    for _block, tx_data, tx in iter_transactions(chain):
        if not isinstance(tx, dict) or tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
            continue
        sender = tx.get("from")
        nonce = tx_nonce(tx)
        if sender and nonce:
            nonces[sender] = max(nonces.get(sender, 0), nonce)
    return nonces


def get_next_nonce(address, chain, mempool=None):
    next_nonce = build_nonces(chain).get(address, 0) + 1
    if mempool:
        pending_nonces = []
        for tx_data in mempool:
            tx = tx_payload(tx_data)
            if isinstance(tx, dict) and tx.get("from") == address:
                nonce = tx_nonce(tx)
                if nonce:
                    pending_nonces.append(nonce)
        while next_nonce in pending_nonces:
            next_nonce += 1
    return next_nonce


def get_balance(address, chain, mempool=None):
    balance = build_balances(chain).get(address, Decimal("0"))
    if mempool:
        for tx_data in mempool:
            tx = tx_payload(tx_data)
            if not isinstance(tx, dict):
                continue
            spend = tx_spend_amount(tx)
            amount = transaction_amount(tx)
            if amount is None or spend is None:
                continue
            if tx.get("from") == address:
                balance -= spend
            if tx.get("to") == address:
                balance += amount
    return float(balance)


def get_total_supply(chain):
    total = Decimal("0")
    for _block, _tx_data, tx in iter_transactions(chain):
        if isinstance(tx, dict) and tx.get("from") == NETWORK:
            amount = Decimal(str(tx.get("base_reward", tx.get("amount", 0))))
            if amount is not None:
                total += amount
    return float(total)


def block_work(block):
    try:
        difficulty = int(block.get("difficulty", 1))
    except Exception:
        difficulty = 1
    return 16 ** max(1, difficulty)


def chain_work(chain):
    return sum(block_work(block) for block in chain)


def chain_tip(chain):
    if not chain:
        return None
    return chain[-1].get("hash")


def get_pending_fee_total(transactions):
    total = Decimal("0")
    for tx_data in transactions:
        tx = tx_payload(tx_data)
        if not isinstance(tx, dict):
            continue
        fee = tx_fee(tx)
        if fee is not None:
            total += fee
    return float(total)


def calculate_reward(height, supply=0):
    # Historical chain rewards
    if height <= 100:
        return 50.0
    elif height <= 200:
        return 25.0
    elif height < 300:
        return 12.5
    elif 300 <= height < 326:
        return 6.25
    elif height <= 840000:
        return 12.5
    else:
        era = (height - 840000) // 840000 + 1
        return max(12.5 / (2 ** era), 0.00000001)

def calculate_next_difficulty(chain):
    config = load_chain_config()
    min_difficulty = int(config.get("min_difficulty", MIN_DIFFICULTY))
    max_difficulty = int(config.get("max_difficulty", MAX_DIFFICULTY))
    interval = int(config.get("difficulty_adjustment_interval", DIFFICULTY_ADJUSTMENT_INTERVAL))
    target_block_time = int(config.get("target_block_time", TARGET_BLOCK_TIME))
    if not chain:
        return min_difficulty
    current = int(chain[-1].get("difficulty", min_difficulty))
    current = max(min_difficulty, min(max_difficulty, current))
    next_height = len(chain) + 1
    if next_height <= interval:
        return current
    if (next_height - 1) % interval != 0:
        return current
    window = chain[-interval:]
    if len(window) < interval:
        return current
    actual_time = float(window[-1]["timestamp"]) - float(window[0]["timestamp"])
    expected_time = target_block_time * (interval - 1)
    if actual_time < expected_time / 2:
        return min(max_difficulty, current + 1)
    if actual_time > expected_time * 2:
        return max(min_difficulty, current - 1)
    return current


def load_public_keys():
    registry = read_json(PUBLIC_KEYS_FILE, [])
    return {
        item.get("address"): item.get("public_key")
        for item in registry
        if item.get("address") and item.get("public_key")
    }


def _normalize_wallet_record(item):
    if not isinstance(item, dict):
        return None
    address = item.get("address") or item.get("wallet")
    if not address:
        return None
    normalized = {
        "wallet": item.get("wallet") or address,
        "address": address,
    }
    if item.get("public_key") is not None:
        normalized["public_key"] = item.get("public_key")
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        normalized["metadata"] = dict(metadata)
    elif metadata is not None:
        normalized["metadata"] = metadata
    for key, value in item.items():
        if key in normalized:
            continue
        if value is not None:
            normalized[key] = value
    return normalized


def register_wallet(address=None, public_key=None, wallet=None, metadata=None):
    target_address = address or wallet
    if not target_address:
        return read_json(WALLETS_FILE, [])
    registry = read_json(WALLETS_FILE, [])
    if not isinstance(registry, list):
        registry = []
    normalized = _normalize_wallet_record({
        "address": target_address,
        "wallet": wallet or target_address,
        "public_key": public_key,
        "metadata": metadata,
    })
    if not normalized:
        return registry

    existing_index = None
    for index, item in enumerate(registry):
        candidate = _normalize_wallet_record(item)
        if candidate and (candidate.get("address") == target_address or candidate.get("wallet") == target_address):
            existing_index = index
            break

    if existing_index is None:
        registry.append(normalized)
    else:
        current = _normalize_wallet_record(registry[existing_index]) or {}
        current["wallet"] = current.get("wallet") or normalized.get("wallet") or target_address
        current["address"] = current.get("address") or normalized.get("address") or target_address
        if normalized.get("public_key") and not current.get("public_key"):
            current["public_key"] = normalized.get("public_key")
        current_meta = {}
        if isinstance(current.get("metadata"), dict):
            current_meta.update(current["metadata"])
        if isinstance(normalized.get("metadata"), dict):
            current_meta.update(normalized["metadata"])
        if current_meta:
            current["metadata"] = current_meta
        elif "metadata" in current:
            current.pop("metadata", None)
        registry[existing_index] = current
    write_json(WALLETS_FILE, registry)
    return registry


def verify_transaction_signature(tx_data, public_keys=None):
    signature = tx_signature(tx_data)
    if signature == MINING_REWARD_SIGNATURE:
        return True, None
    tx = tx_payload(tx_data)
    if not isinstance(tx, dict):
        return False, "Transaction payload must be an object"
    sender = tx.get("from")
    if sender == NETWORK:
        return False, "Only mining rewards can spend from NETWORK"
    if not signature:
        return False, "Missing transaction signature"
    public_keys = public_keys if public_keys is not None else load_public_keys()
    public_key_hex = public_keys.get(sender)
    if not public_key_hex and isinstance(tx_data, dict):
        embedded_pub = tx_data.get("public_key") or tx.get("public_key")
        if embedded_pub:
            if hashlib.sha256(str(embedded_pub).encode()).hexdigest() != sender:
                return False, "Public key does not match sender address"
            public_key_hex = str(embedded_pub)
            public_keys[sender] = public_key_hex
            register_public_key(sender, public_key_hex)
    if not public_key_hex:
        return False, "Sender public key is not registered"
    try:
        public_key = VerifyingKey.from_string(
            bytes.fromhex(public_key_hex),
            curve=SECP256k1,
        )
        raw_signature = bytes.fromhex(signature)
    except Exception:
        return False, "Invalid public key or signature encoding"
    signing_payload = tx_signing_payload(tx)
    messages = [
        canonical_json(signing_payload).encode(),
        json.dumps(signing_payload, sort_keys=True).encode(),
        json.dumps(signing_payload).encode(),
        canonical_json(tx).encode(),
        json.dumps(tx, sort_keys=True).encode(),
        json.dumps(tx).encode(),
    ]
    for message in messages:
        try:
            public_key.verify(raw_signature, message)
            return True, None
        except Exception:
            pass
    return False, "Invalid transaction signature"


def transaction_duplicate_error(tx_data, chain=None, mempool=None):
    current_txid = tx_id(tx_data)
    if not current_txid:
        return "Transaction txid is invalid"
    for block in chain or []:
        for existing_tx in block.get("transactions", []):
            if tx_id(existing_tx) == current_txid:
                return "Transaction already exists in chain"
    if mempool:
        for pending in mempool:
            try:
                if tx_id(pending) == current_txid:
                    return "Transaction already exists in mempool"
            except Exception:
                continue
    return None


def replay_attack_error(tx_data, chain=None, mempool=None):
    tx = tx_payload(tx_data)
    if not isinstance(tx, dict):
        return None
    sender = tx.get("from")
    nonce = tx_nonce(tx)
    if not sender or nonce is None:
        return None
    for block, tx_entry, existing_tx in iter_transactions(chain or []):
        if not isinstance(existing_tx, dict) or existing_tx.get("from") != sender:
            continue
        existing_nonce = tx_nonce(existing_tx)
        if existing_nonce and existing_nonce == nonce:
            return f"Invalid nonce, expected {get_next_nonce(sender, chain, mempool)}"
    if mempool:
        for pending in mempool:
            pending_tx = tx_payload(pending)
            if isinstance(pending_tx, dict) and pending_tx.get("from") == sender:
                pending_nonce = tx_nonce(pending_tx)
                if pending_nonce and pending_nonce == nonce:
                    return f"Invalid nonce, expected {get_next_nonce(sender, chain, mempool)}"
    return None


def double_spend_error(tx_data, chain=None, mempool=None):
    tx = tx_payload(tx_data)
    if not isinstance(tx, dict):
        return None
    sender = tx.get("from")
    spend = tx_spend_amount(tx)
    if not sender or spend is None:
        return None
    available = Decimal(str(get_balance(sender, chain)))
    if mempool:
        for pending in mempool:
            pending_tx = tx_payload(pending)
            if not isinstance(pending_tx, dict):
                continue
            pending_spend = tx_spend_amount(pending_tx)
            if pending_tx.get("from") == sender and pending_spend:
                available -= pending_spend
    if spend > available:
        return "Double spend detected: insufficient funds for pending transactions"
    return None


def validate_transaction(tx_data, chain, mempool=None, public_keys=None, enforce_nonce=True):
    if not isinstance(tx_data, dict):
        return False, "Transaction payload must be an object"
    tx = tx_payload(tx_data)
    if not isinstance(tx, dict):
        return False, "Transaction payload must be an object"
    current_txid = tx_id(tx_data)
    if not current_txid:
        return False, "Transaction txid is invalid"
    sender = tx.get("from")
    receiver = tx.get("to")
    amount = transaction_amount(tx)
    if not sender or not receiver:
        return False, "Transaction must include from and to"
    expected_txid = hash_data(tx_signing_payload(tx))
    if tx.get("txid") and tx["txid"] != expected_txid:
        return False, "Transaction txid does not match payload"
    if amount is None:
        return False, "Transaction amount must be positive"
    fee = tx_fee(tx)
    if fee is None:
        return False, "Transaction fee must be zero or positive"
    if sender == receiver:
        return False, "Sender and receiver must be different"
    if mempool is not None:
        duplicate_error = transaction_duplicate_error(tx_data, chain, mempool)
        if duplicate_error:
            return False, duplicate_error
    ok, error = verify_transaction_signature(tx_data, public_keys)
    if not ok:
        return False, error
    if tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
        return True, None
    if mempool is not None:
        double_spend_error_message = double_spend_error(tx_data, chain, mempool)
        if double_spend_error_message:
            return False, double_spend_error_message
    if enforce_nonce:
        nonce = tx_nonce(tx)
        if nonce is None:
            return False, "Transaction nonce must be a positive integer"
        replay_error = replay_attack_error(tx_data, chain, mempool)
        if replay_error:
            return False, replay_error
        expected_nonce = get_next_nonce(sender, chain, mempool)
        if nonce != expected_nonce:
            return False, f"Invalid nonce, expected {expected_nonce}"
    spend = tx_spend_amount(tx)
    available = Decimal(str(get_balance(sender, chain)))
    if mempool:
        for pending in mempool:
            pending_tx = tx_payload(pending)
            pending_spend = tx_spend_amount(pending_tx)
            if isinstance(pending_tx, dict) and pending_tx.get("from") == sender and pending_spend:
                available -= pending_spend
    if spend > available:
        return False, "Insufficient funds"
    return True, None


def validate_block_transactions(block, prior_chain):
    working_balances = build_balances(prior_chain)
    working_nonces = build_nonces(prior_chain)
    public_keys = load_public_keys()
    seen_txids = set()
    reward_txs = []
    normal_txs = []
    fee_total = Decimal("0")

    for tx_data in block.get("transactions", []):
        tx = tx_payload(tx_data)
        current_txid = tx_id(tx_data)
        if current_txid in seen_txids:
            return False, "Block contains duplicate transaction IDs"
        seen_txids.add(current_txid)
        if tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
            reward_txs.append(tx_data)
        else:
            normal_txs.append(tx_data)

    if len(reward_txs) > 1:
        return False, "Block contains multiple mining rewards"

    for tx_data in normal_txs:
        tx = tx_payload(tx_data)
        valid, error = validate_transaction(
            tx_data,
            prior_chain,
            None,
            public_keys,
            enforce_nonce=False,
        )
        if not valid:
            return False, error
        sender = tx["from"]
        receiver = tx["to"]
        expected_nonce = working_nonces.get(sender, 0) + 1
        nonce = tx_nonce(tx)
        if nonce != expected_nonce:
            return False, f"Invalid nonce for {sender}, expected {expected_nonce}"
        spend = tx_spend_amount(tx)
        amount = transaction_amount(tx)
        fee = tx_fee(tx)
        if working_balances.get(sender, Decimal("0")) < spend:
            return False, f"Insufficient funds for {sender}"
        working_balances[sender] = working_balances.get(sender, Decimal("0")) - spend
        working_balances[receiver] = working_balances.get(receiver, Decimal("0")) + amount
        working_nonces[sender] = nonce
        fee_total += fee

    expected_reward = Decimal(str(calculate_reward(len(prior_chain), get_total_supply(prior_chain))))
    if reward_txs:
        reward = tx_payload(reward_txs[0])
        if reward.get("from") != NETWORK:
            return False, "Mining reward must come from NETWORK"
        if tx_fee(reward) not in (Decimal("0"), None):
            return False, "Mining reward fee must be zero"
        base_reward = Decimal(str(reward.get("base_reward", reward.get("amount", 0))))
        fees = Decimal(str(reward.get("fees", 0)))
        amount = transaction_amount(reward)
        if base_reward != expected_reward:
            return False, f"Invalid base reward, expected {float(expected_reward)}"
        if fees != fee_total:
            return False, f"Invalid reward fees, expected {float(fee_total)}"
        if amount != base_reward + fees:
            return False, "Reward amount must equal base reward plus fees"
    elif expected_reward > 0 or fee_total > 0:
        return False, "Block is missing mining reward"

    return True, None


def validate_block(
    block,
    previous_block=None,
    full_transactions=False,
    prior_chain=None,
    check_future_time=False,
    prefix="Block",
):
    required = ("index", "timestamp", "transactions", "proof", "difficulty", "previous_hash", "hash")
    for field in required:
        if field not in block:
            return False, f"{prefix} missing {field}"
    expected_hash = hash_block(block)
    if block["hash"] != expected_hash:
        return False, f"{prefix} hash does not match block contents"
    difficulty = int(block.get("difficulty", 1))
    if difficulty < 1:
        return False, f"{prefix} difficulty must be at least 1"
    try:
        timestamp = float(block["timestamp"])
    except Exception:
        return False, f"{prefix} timestamp is invalid"
    max_future_time = int(load_chain_config().get("max_future_block_time", MAX_FUTURE_BLOCK_TIME))
    if check_future_time and timestamp > time.time() + max_future_time:
        return False, f"{prefix} timestamp is too far in the future"
    if "merkle_root" in block:
        expected_merkle = compute_merkle_root(block.get("transactions", []))
        if block["merkle_root"] != expected_merkle:
            return False, f"{prefix} merkle_root does not match transactions"
    pow_hash = hashlib.sha256(
        f'{block["previous_hash"]}{block["proof"]}'.encode()
    ).hexdigest()
    merkle_pow_hash = hashlib.sha256(
        f'{block["previous_hash"]}{block.get("merkle_root", "")}{block["proof"]}'.encode()
    ).hexdigest()
    if not (pow_hash.startswith("0" * difficulty) or merkle_pow_hash.startswith("0" * difficulty)):
        return False, f"{prefix} proof of work is invalid"
    if previous_block is None:
        if block["previous_hash"] != "0":
            return False, f"{prefix} genesis previous_hash must be 0"
    else:
        if block["previous_hash"] != previous_block.get("hash"):
            return False, f"{prefix} previous_hash does not match previous block"
        if block["index"] != previous_block.get("index", 0) + 1:
            return False, f"{prefix} index is out of order"
        if timestamp < float(previous_block.get("timestamp", 0)):
            return False, f"{prefix} timestamp must not be before previous block"
    if prior_chain is not None and previous_block is not None:
        expected_difficulty = calculate_next_difficulty(prior_chain)
        if difficulty != expected_difficulty:
            return False, (
                f"{prefix} difficulty {difficulty} does not match "
                f"expected {expected_difficulty}"
            )
    reward_count = 0
    seen_txids = set()
    for tx_data in block.get("transactions", []):
        tx = tx_payload(tx_data)
        if not isinstance(tx, dict):
            return False, f"{prefix} contains a malformed transaction"
        amount = transaction_amount(tx)
        fee = tx_fee(tx)
        if amount is None:
            return False, f"{prefix} contains a non-positive amount"
        if fee is None:
            return False, f"{prefix} contains an invalid fee"
        if tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
            reward_count += 1
        current_txid = tx_id(tx_data)
        if current_txid in seen_txids:
            return False, f"{prefix} contains a duplicate transaction"
        seen_txids.add(current_txid)
    if reward_count > 1:
        return False, f"{prefix} contains multiple mining rewards"
    if full_transactions:
        valid, error = validate_block_transactions(block, prior_chain or [])
        if not valid:
            return False, f"{prefix} transaction validation failed: {error}"
    return True, None


def validate_candidate_block(block, check_future_time=True, prefix="Candidate block", prior_chain=None):
    required = ("index", "timestamp", "transactions", "proof", "difficulty", "previous_hash", "hash")
    for field in required:
        if field not in block:
            return False, f"{prefix} missing {field}"
    expected_hash = hash_block(block)
    if block["hash"] != expected_hash:
        return False, f"{prefix} hash does not match block contents"
    try:
        difficulty = int(block.get("difficulty", 1))
    except Exception:
        return False, f"{prefix} difficulty is invalid"
    if difficulty < 1:
        return False, f"{prefix} difficulty must be at least 1"
    if prior_chain is not None:
        expected_difficulty = calculate_next_difficulty(prior_chain)
        if difficulty != expected_difficulty:
            return False, (
                f"{prefix} difficulty {difficulty} does not match "
                f"expected {expected_difficulty}"
            )
    try:
        timestamp = float(block["timestamp"])
    except Exception:
        return False, f"{prefix} timestamp is invalid"
    max_future_time = int(load_chain_config().get("max_future_block_time", MAX_FUTURE_BLOCK_TIME))
    if check_future_time and timestamp > time.time() + max_future_time:
        return False, f"{prefix} timestamp is too far in the future"
    if "merkle_root" in block:
        expected_merkle = compute_merkle_root(block.get("transactions", []))
        if block["merkle_root"] != expected_merkle:
            return False, f"{prefix} merkle_root does not match transactions"
    pow_hash = hashlib.sha256(
        f'{block["previous_hash"]}{block["proof"]}'.encode()
    ).hexdigest()
    merkle_pow_hash = hashlib.sha256(
        f'{block["previous_hash"]}{block.get("merkle_root", "")}{block["proof"]}'.encode()
    ).hexdigest()
    if not (pow_hash.startswith("0" * difficulty) or merkle_pow_hash.startswith("0" * difficulty)):
        return False, f"{prefix} proof of work is invalid"
    reward_count = 0
    seen_txids = set()
    for tx_data in block.get("transactions", []):
        tx = tx_payload(tx_data)
        if not isinstance(tx, dict):
            return False, f"{prefix} contains a malformed transaction"
        amount = transaction_amount(tx)
        fee = tx_fee(tx)
        if amount is None:
            return False, f"{prefix} contains a non-positive amount"
        if fee is None:
            return False, f"{prefix} contains an invalid fee"
        if tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
            reward_count += 1
        current_txid = tx_id(tx_data)
        if current_txid in seen_txids:
            return False, f"{prefix} contains a duplicate transaction"
        seen_txids.add(current_txid)
    if reward_count > 1:
        return False, f"{prefix} contains multiple mining rewards"
    return True, None


def validate_chain(chain):
    if not isinstance(chain, list) or not chain:
        return False, "Chain is empty"
    for index, block in enumerate(chain):
        previous = chain[index - 1] if index else None
        ok, error = validate_block(
            block,
            previous_block=previous,
            full_transactions=index > 0,
            prior_chain=chain[:index],
            check_future_time=False,
            prefix=f"Block {block.get('index', index + 1)}",
        )
        if not ok:
            return False, error
    return True, None


def create_genesis_block():
    config = load_chain_config()
    block = {
        "index": 1,
        "timestamp": float(config.get("genesis_timestamp", time.time())),
        "genesis_message": config.get("genesis_message", "KWD genesis"),
        "network_id": config.get("network_id", "kwd-local"),
        "transactions": [],
        "proof": 0,
        "difficulty": int(config.get("min_difficulty", MIN_DIFFICULTY)),
        "previous_hash": "0",
    }
    proof = 0
    while True:
        block["proof"] = proof
        if hashlib.sha256(f"0{proof}".encode()).hexdigest().startswith(
            "0" * int(block["difficulty"])
        ):
            break
        proof += 1
    block["hash"] = hash_block(block)
    return block


def backup_file(path):
    data = read_json(path, None)
    if data is None:
        return None
    backup_path = f"{path}.backup-{int(time.time())}"
    temp_path = f"{backup_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
    os.replace(temp_path, backup_path)
    return backup_path


def recover_state_file(path, default=None):
    if not os.path.exists(path):
        if default is not None:
            write_json(path, default)
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        write_json(path, payload)
        return payload
    except (json.JSONDecodeError, OSError):
        backup_candidates = sorted(
            [candidate for candidate in os.listdir('.') if candidate.startswith(f"{path}.backup-")],
            reverse=True,
        )
        for candidate in backup_candidates:
            try:
                with open(candidate, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                write_json(path, payload)
                return payload
            except (json.JSONDecodeError, OSError):
                continue
        if default is not None:
            write_json(path, default)
            return default
        return None


def reset_chain():
    ensure_chain_config()
    backup_path = backup_file(CHAIN_FILE)
    chain = [create_genesis_block()]
    write_json(CHAIN_FILE, chain)
    write_json(MEMPOOL_FILE, [])
    return chain, backup_path


def create_wallet():
    private_key = SigningKey.generate(curve=SECP256k1)
    public_key = private_key.verifying_key
    private_hex = private_key.to_string().hex()
    public_hex = public_key.to_string().hex()
    address = hashlib.sha256(public_hex.encode()).hexdigest()
    registry = read_json(PUBLIC_KEYS_FILE, [])
    if not any(item.get("address") == address for item in registry):
        registry.append({"address": address, "public_key": public_hex})
        write_json(PUBLIC_KEYS_FILE, registry)
    register_wallet(address=address, public_key=public_hex, wallet=address, metadata={"source": "local"})
    store_wallet_secret(address, private_hex)
    return {
        "private_key": private_hex,
        "public_key": public_hex,
        "address": address,
    }


def wallet_from_private_key(private_key_hex):
    private_key = SigningKey.from_string(
        bytes.fromhex(private_key_hex),
        curve=SECP256k1,
    )
    public_key = private_key.verifying_key
    public_hex = public_key.to_string().hex()
    address = hashlib.sha256(public_hex.encode()).hexdigest()
    return private_key, {
        "private_key": private_key_hex,
        "public_key": public_hex,
        "address": address,
    }


def register_public_key(address, public_key_hex):
    registry = read_json(PUBLIC_KEYS_FILE, [])
    if not any(item.get("address") == address for item in registry):
        registry.append({"address": address, "public_key": public_key_hex})
        write_json(PUBLIC_KEYS_FILE, registry)


def create_signed_transaction(private_key_hex, receiver, amount, fee=None, nonce=None, chain=None, mempool=None):
    private_key, wallet = wallet_from_private_key(private_key_hex)
    register_public_key(wallet["address"], wallet["public_key"])
    tx = {
        "from": wallet["address"],
        "to": receiver,
        "amount": float(Decimal(str(amount))),
        "fee": float(fee if fee is not None else load_chain_config().get("default_fee", DEFAULT_FEE)),
        "timestamp": time.time(),
        "nonce": nonce if nonce is not None else get_next_nonce(
            wallet["address"],
            chain if chain is not None else read_json(CHAIN_FILE, []),
            mempool if mempool is not None else read_json(MEMPOOL_FILE, []),
        ),
    }
    tx["txid"] = hash_data(tx_signing_payload(tx))
    signature = private_key.sign(canonical_json(tx_signing_payload(tx)).encode())
    return {
        "transaction": tx,
        "signature": signature.hex(),
        "public_key": wallet["public_key"],
    }



