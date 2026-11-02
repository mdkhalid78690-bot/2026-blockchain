import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, Response, jsonify, redirect, request
from flask_cors import CORS
from flask.testing import FlaskClient

from core import (
    CHAIN_FILE,
    CHAIN_CONFIG_FILE,
    WALLET_SECRETS_FILE,
    MEMPOOL_FILE,
    ORPHAN_BLOCKS_FILE,
    PEERS_FILE,
    WALLETS_FILE,
    PUBLIC_KEYS_FILE,
    BLACKLIST_FILE,
    PEER_FAILURES_FILE,
    PEER_REPUTATION_FILE,
    PEER_BLACKLIST_DURATION,
    MAX_PEER_FAILURES,
    DIFFICULTY_ADJUSTMENT_INTERVAL,
    MAX_FUTURE_BLOCK_TIME,
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    TARGET_BLOCK_TIME,
    chain_work,
    calculate_next_difficulty,
    calculate_reward,
    create_signed_transaction,
    create_wallet,
    get_balance,
    get_next_nonce,
    get_pending_fee_total,
    get_total_supply,
    iter_transactions,
    load_chain_config,
    load_public_keys,
    load_wallet_secret,
    normalize_peer,
    read_json,
    reset_chain,
    register_public_key,
    register_wallet,
    backup_file,
    recover_state_file,
    tx_id,
    tx_payload,
    tx_signature,
    transaction_duplicate_error,
    validate_block,
    validate_candidate_block,
    validate_chain as validate_chain_data,
    validate_transaction,
    wallet_from_private_key,
    write_json,
    save_mempool,
    MINING_REWARD_SIGNATURE,
)


app = Flask(__name__)
CORS(app)

if not hasattr(FlaskClient, "get_json"):
    def _compat_client_get_json(self):
        response = getattr(self, "_last_response", None)
        if response is None:
            raise RuntimeError("No response available")
        return response.get_json()

    FlaskClient.get_json = _compat_client_get_json

if not hasattr(FlaskClient, "_kwd_open_wrapper"):
    _original_open = FlaskClient.open

    def _compat_client_open(self, *args, **kwargs):
        response = _original_open(self, *args, **kwargs)
        self._last_response = response
        return response

    FlaskClient.open = _compat_client_open
    FlaskClient._kwd_open_wrapper = True

RATE_LIMIT_STATE = {"requests": {}, "bans": {}}
RATE_LIMIT_CONFIG_SIGNATURE = None
NODE_EVENTS_FILE = "node_events.json"
AUDIT_LOG_FILE = "audit_log.json"
APPROVAL_HISTORY_FILE = "approval_history.json"
START_TIME = time.time()


def format_human_time(timestamp):
    if timestamp in (None, "", 0):
        return "N/A"
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return str(timestamp)
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return str(timestamp)


def format_human_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _current_rate_limit_signature():
    security_config = load_chain_config().get("security", {})
    try:
        config_mtime = os.path.getmtime(CHAIN_CONFIG_FILE)
    except OSError:
        config_mtime = 0
    return (
        security_config.get("rate_limit"),
        security_config.get("rate_limit_window_seconds", 60),
        security_config.get("rate_limit_ban_seconds", 60),
        config_mtime,
    )


def _reset_rate_limit_state_if_needed():
    global RATE_LIMIT_CONFIG_SIGNATURE
    signature = _current_rate_limit_signature()
    if signature != RATE_LIMIT_CONFIG_SIGNATURE:
        RATE_LIMIT_STATE["requests"] = {}
        RATE_LIMIT_STATE["bans"] = {}
        RATE_LIMIT_CONFIG_SIGNATURE = signature


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def load_node_events():
    return read_json(NODE_EVENTS_FILE, [])


def append_node_event(event_type, message, details=None):
    events = load_node_events()
    events.append({
        "timestamp": time.time(),
        "type": event_type,
        "message": message,
        "details": details or {},
    })
    write_json(NODE_EVENTS_FILE, events[-50:])
    return events[-1]


def load_audit_log():
    return read_json(AUDIT_LOG_FILE, [])


def append_audit_event(event_type, message, details=None):
    log = load_audit_log()
    log.append({
        "timestamp": time.time(),
        "type": event_type,
        "message": message,
        "details": details or {},
    })
    write_json(AUDIT_LOG_FILE, log[-100:])
    return log[-1]


def load_approval_history():
    return read_json(APPROVAL_HISTORY_FILE, [])


def append_approval_event(action, approved, details=None):
    history = load_approval_history()
    history.append({
        "timestamp": time.time(),
        "action": action,
        "approved": approved,
        "details": details or {},
    })
    write_json(APPROVAL_HISTORY_FILE, history[-100:])
    return history[-1]


def get_auth_token():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_header = auth_header[len("Bearer "):].strip()
    return request.args.get("auth_token") or request.headers.get("X-Auth-Token") or auth_header


def build_peer_headers(path, payload=None):
    security_config = load_chain_config().get("security", {})
    shared_secret = security_config.get("peer_shared_secret")
    node_config = read_json("node_config.json", {})
    headers = {
        "X-Node-Id": node_config.get("node_id", "unknown"),
        "X-Timestamp": str(int(time.time())),
    }
    if not shared_secret:
        return headers
    body = payload if payload is not None else ""
    if isinstance(body, (dict, list)):
        body = json.dumps(body, sort_keys=True, separators=(",", ":"))
    elif not isinstance(body, str):
        body = str(body)
    signature = hmac.new(
        shared_secret.encode("utf-8"),
        f"{path}:{headers['X-Timestamp']}:{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["X-Peer-Signature"] = signature
    return headers


def signed_get(url, **kwargs):
    headers = build_peer_headers(kwargs.pop("path", ""))
    kwargs.setdefault("headers", {})
    kwargs["headers"].update(headers)
    return requests.get(url, **kwargs)


def signed_post(url, **kwargs):
    headers = build_peer_headers(kwargs.pop("path", ""), payload=kwargs.get("json"))
    kwargs.setdefault("headers", {})
    kwargs["headers"].update(headers)
    return requests.post(url, **kwargs)


def is_admin_authorized():
    security_config = load_chain_config().get("security", {})
    admin_token = security_config.get("admin_token")
    if not admin_token:
        return True
    provided_token = get_auth_token()
    return provided_token == admin_token


def get_peer_signature_headers():
    return {
        "node_id": request.headers.get("X-Node-Id", ""),
        "timestamp": request.headers.get("X-Timestamp", ""),
        "signature": request.headers.get("X-Peer-Signature", ""),
    }


def is_peer_signature_valid():
    security_config = load_chain_config().get("security", {})
    shared_secret = security_config.get("peer_shared_secret")
    if not shared_secret:
        return True
    headers = get_peer_signature_headers()
    if not headers["timestamp"] or not headers["signature"]:
        return False
    payload_candidates = []
    raw_payload = request.get_data(cache=True, as_text=True)
    if raw_payload:
        payload_candidates.append(raw_payload)
    try:
        parsed_json = request.get_json(silent=True)
        if parsed_json is not None:
            payload_candidates.append(json.dumps(parsed_json, sort_keys=True, separators=(",", ":")))
    except Exception:
        pass
    if not payload_candidates:
        payload_candidates.append("")
    for payload in payload_candidates:
        expected = hmac.new(
            shared_secret.encode("utf-8"),
            f"{request.path}:{headers['timestamp']}:{payload}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, headers["signature"]):
            return True
    return False


def requires_peer_auth():
    return request.path in {"/register_peer", "/sync_peers", "/bootstrap", "/sync_chain", "/sync_mempool", "/peer_health"}


def is_browser_safe_read_request():
    return request.method in {"GET", "HEAD", "OPTIONS"} and requires_peer_auth()


def is_peer_auth_authorized(data=None):
    required_token = get_peer_registration_token()
    if not required_token:
        return True
    token_source = data or {}
    provided_token = token_source.get("auth_token") or get_auth_token() or ""
    return provided_token == required_token


def enforce_public_access_controls():
    security_config = load_chain_config().get("security", {})
    if not security_config.get("public_api_enabled", True):
        if request.path in {"/healthz", "/deployment_status", "/deployment_control", "/audit_log", "/approval_history"}:
            return jsonify({"error": "Public API access disabled"}), 403
    if security_config.get("rollout_safety_mode"):
        protected_paths = {"/healthz", "/deployment_status", "/deployment_control", "/bootstrap_config", "/audit_log", "/approval_history"}
        if request.path in protected_paths:
            return jsonify({"error": "Rollout safety mode active"}), 403
    if security_config.get("rollout_pending") and request.path in {"/deployment_control", "/bootstrap_config", "/audit_log", "/approval_history"}:
        if not is_admin_authorized():
            return jsonify({"error": "Admin authentication required"}), 403
    return None


def enforce_security():
    _reset_rate_limit_state_if_needed()
    public_access_control_error = enforce_public_access_controls()
    if public_access_control_error is not None:
        return public_access_control_error
    if requires_peer_auth():
        if is_browser_safe_read_request():
            if not get_peer_registration_token():
                return None
            if is_peer_auth_authorized():
                return None
            return jsonify({"error": "Peer registration authorization failed"}), 403
        if is_peer_auth_authorized():
            return None
        if is_peer_signature_valid():
            return None
        return jsonify({"error": "Peer signature verification failed"}), 403
    security_config = load_chain_config().get("security", {})
    rate_limit = security_config.get("rate_limit")
    if rate_limit is None or int(rate_limit) <= 0:
        return None
    now = time.time()
    ip = get_client_ip()
    ban_until = RATE_LIMIT_STATE["bans"].get(ip)
    if ban_until and now < ban_until:
        return jsonify({"error": "Rate limit exceeded. Please retry later."}), 429
    if ban_until and now >= ban_until:
        RATE_LIMIT_STATE["bans"].pop(ip, None)
    window_seconds = max(1, int(security_config.get("rate_limit_window_seconds", 60)))
    bucket = RATE_LIMIT_STATE["requests"].setdefault(ip, deque())
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    bucket.append(now)
    if len(bucket) > int(rate_limit):
        ban_seconds = max(1, int(security_config.get("rate_limit_ban_seconds", 60)))
        RATE_LIMIT_STATE["bans"][ip] = now + ban_seconds
        return jsonify({"error": "Rate limit exceeded. Please retry later."}), 429
    return None


@app.before_request
def before_request():
    if request.method == "OPTIONS":
        return None
    return enforce_security()


def load_chain():
    data = read_json(CHAIN_FILE, [])
    if isinstance(data, list):
        return data
    return []


def load_mempool():
    data = read_json(MEMPOOL_FILE, [])
    if isinstance(data, list):
        print(f"[load_mempool] loaded {len(data)} pending txs")
        return data
    print("[load_mempool] mempool data invalid, resetting to empty list")
    return []


def load_peers(allow_blacklisted=False):
    peers = read_json(PEERS_FILE, [])
    if isinstance(peers, str):
        peers = [peers]
    config = load_chain_config()
    seed_nodes = config.get("seed_nodes", []) or []
    self_url = get_self_peer_url()
    changed = False
    for seed in seed_nodes:
        normalized = normalize_peer(seed)
        if not normalized or normalized.rstrip("/") == self_url.rstrip("/"):
            continue
        stored = normalized.replace("http://", "").replace("https://", "")
        if stored not in peers:
            peers.append(stored)
            changed = True
    if changed:
        write_json(PEERS_FILE, peers)
    return peers


def load_orphans():
    return read_json(ORPHAN_BLOCKS_FILE, [])


def load_blacklist():
    return read_json(BLACKLIST_FILE, [])


def save_blacklist(entries):
    write_json(BLACKLIST_FILE, entries)


def load_peer_failures():
    return read_json(PEER_FAILURES_FILE, {})


def save_peer_failures(entries):
    write_json(PEER_FAILURES_FILE, entries)


def load_peer_reputation():
    return read_json(PEER_REPUTATION_FILE, {})


def save_peer_reputation(entries):
    write_json(PEER_REPUTATION_FILE, entries)


def get_stored_peer(peer):
    normalized = normalize_peer(peer)
    if not normalized:
        return None
    return normalized.replace("http://", "").replace("https://", "").rstrip("/")


def cleanup_blacklist():
    blacklist = load_blacklist()
    now = time.time()
    active = []
    expired = []
    for entry in blacklist:
        duration = entry.get("duration", PEER_BLACKLIST_DURATION)
        if now - entry.get("timestamp", 0) >= duration:
            expired.append(entry)
        else:
            active.append(entry)
    if len(active) != len(blacklist):
        save_blacklist(active)
    return expired


def is_peer_blacklisted(peer):
    cleanup_blacklist()
    stored = get_stored_peer(peer)
    if not stored:
        return False
    return any(entry.get("peer") == stored for entry in load_blacklist())


def blacklist_peer(peer, reason, duration=None):
    stored = get_stored_peer(peer)
    if not stored:
        return False
    blacklist = load_blacklist()
    if not any(entry.get("peer") == stored for entry in blacklist):
        blacklist.append({
            "peer": stored,
            "reason": reason,
            "timestamp": time.time(),
            "duration": duration or PEER_BLACKLIST_DURATION,
        })
        save_blacklist(blacklist)
    failures = load_peer_failures()
    if stored in failures:
        failures.pop(stored, None)
        save_peer_failures(failures)
    return True


def unblacklist_peer(peer):
    stored = get_stored_peer(peer)
    if not stored:
        return False
    blacklist = load_blacklist()
    filtered = [entry for entry in blacklist if entry.get("peer") != stored]
    if len(filtered) == len(blacklist):
        return False
    save_blacklist(filtered)
    return True


def record_peer_failure(peer, error, threshold=MAX_PEER_FAILURES):
    stored = get_stored_peer(peer)
    if not stored or is_peer_blacklisted(stored):
        return
    failures = load_peer_failures()
    failures[stored] = failures.get(stored, 0) + 1
    if failures[stored] >= threshold:
        blacklist_peer(stored, error)
        failures.pop(stored, None)
    save_peer_failures(failures)
    reputation = load_peer_reputation()
    reputation[stored] = reputation.get(stored, {})
    reputation[stored]["score"] = max(-100, reputation[stored].get("score", 0) - 10)
    reputation[stored]["last_updated"] = time.time()
    save_peer_reputation(reputation)


def update_peer_reputation(peer, delta, reason=None):
    stored = get_stored_peer(peer)
    if not stored:
        return None
    reputation = load_peer_reputation()
    entry = reputation.get(stored, {})
    entry["score"] = entry.get("score", 0) + int(delta)
    entry["score"] = max(-100, min(100, entry["score"]))
    if reason:
        entry["last_reason"] = reason
    entry["last_updated"] = time.time()
    reputation[stored] = entry
    save_peer_reputation(reputation)
    return reputation[stored]


def get_peer_reputation(peer):
    stored = get_stored_peer(peer)
    if not stored:
        return {"score": 0}
    return load_peer_reputation().get(stored, {"score": 0})


def cleanup_orphans(max_age_seconds=86400):
    chain = load_chain()
    attached = attach_connectable_orphans(chain)
    if attached:
        write_json(CHAIN_FILE, chain)
    orphans = load_orphans()
    cutoff = time.time() - max_age_seconds
    stale = [orphan for orphan in orphans if orphan.get("last_seen", 0) < cutoff]
    if stale:
        write_json(ORPHAN_BLOCKS_FILE, [orphan for orphan in orphans if orphan not in stale])
    return {"attached": attached, "removed_stale": [orphan.get("hash") for orphan in stale]}


def broadcast_transaction(tx_data):
    peers = load_peers()
    print(f"[broadcast_transaction] broadcasting tx {tx_id(tx_data)} to {len(peers)} peers")
    for peer in peers:
        peer_url = normalize_peer(peer)
        if not peer_url:
            continue
        try:
            signed_post(f"{peer_url}/receive_transaction", path="/receive_transaction", json=tx_data, timeout=5)
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            print(f"Transaction broadcast failed for {peer}: {exc}")


def broadcast_block(block):
    peers = load_peers()
    print(f"[broadcast_block] broadcasting block {block.get('hash')} index={block.get('index')} to {len(peers)} peers")
    for peer in peers:
        peer_url = normalize_peer(peer)
        if not peer_url:
            continue
        try:
            signed_post(f"{peer_url}/receive_block", path="/receive_block", json=block, timeout=5)
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            print(f"Block broadcast failed for {peer}: {exc}")


def save_orphan_block(block, reason):
    orphans = load_orphans()
    block_hash = block.get("hash")
    if not block_hash:
        return {"stored": False, "reason": "Missing block hash"}
    for orphan in orphans:
        if orphan.get("block", {}).get("hash") == block_hash:
            orphan["reason"] = reason
            orphan["last_seen"] = time.time()
            write_json(ORPHAN_BLOCKS_FILE, orphans)
            return {"stored": False, "reason": "Orphan already stored"}
    orphans.append({
        "hash": block_hash,
        "previous_hash": block.get("previous_hash"),
        "index": block.get("index"),
        "reason": reason,
        "first_seen": time.time(),
        "last_seen": time.time(),
        "block": block,
    })
    write_json(ORPHAN_BLOCKS_FILE, orphans)
    return {"stored": True, "reason": reason}


def remove_mined_transactions(block):
    mined_txids = {tx_id(tx) for tx in block.get("transactions", [])}
    mempool_data = load_mempool()
    original_count = len(mempool_data)
    mempool_data = [tx for tx in mempool_data if tx_id(tx) not in mined_txids]
    removed_count = original_count - len(mempool_data)
    if removed_count:
        print(f"[remove_mined_transactions] removed {removed_count} mined tx(s) from mempool after block {block.get('hash')}")
        save_mempool(mempool_data, reason=f"remove mined txs from block {block.get('hash')}")
    return removed_count


def attach_connectable_orphans(chain):
    attached = []
    changed = True
    while changed:
        changed = False
        orphans = load_orphans()
        remaining = []
        tip = chain[-1] if chain else None
        for orphan in orphans:
            block = orphan.get("block", {})
            if tip and block.get("previous_hash") == tip.get("hash"):
                valid, error = validate_block(
                    block,
                    previous_block=tip,
                    full_transactions=True,
                    prior_chain=chain,
                    prefix="Orphan block",
                )
                if valid:
                    chain.append(block)
                    remove_mined_transactions(block)
                    attached.append(block.get("hash"))
                    changed = True
                else:
                    orphan["reason"] = error
                    remaining.append(orphan)
            else:
                remaining.append(orphan)
        write_json(ORPHAN_BLOCKS_FILE, remaining)
    return attached


def reconcile_mempool(chain):
    mempool_data = load_mempool()
    valid_mempool = []
    removed = []
    for tx_data in mempool_data:
        valid, error = validate_transaction(tx_data, chain, valid_mempool)
        if valid:
            valid_mempool.append(tx_data)
        else:
            removed.append({"txid": tx_id(tx_data), "error": error})
    if removed:
        save_mempool(valid_mempool, reason="reconcile mempool against chain")
        print(f"[reconcile_mempool] removed {len(removed)} invalid or duplicate tx(s)")
    return removed


def peer_health_data():
    results = []
    failures = load_peer_failures()
    for peer in load_peers():
        stored = get_stored_peer(peer)
        failure_count = failures.get(stored, 0) if stored else 0
        if is_peer_blacklisted(peer):
            entry = next((item for item in load_blacklist() if item.get("peer") == stored), {})
            results.append({
                "peer": peer,
                "online": False,
                "error": "Peer is blacklisted",
                "blacklisted": True,
                "blacklist_reason": entry.get("reason"),
                "blacklist_expires": entry.get("timestamp", 0) + entry.get("duration", PEER_BLACKLIST_DURATION),
                "failure_count": failure_count,
                "reputation": get_peer_reputation(peer),
            })
            continue
        peer_url = normalize_peer(peer)
        started = time.time()
        if not peer_url:
            results.append({"peer": peer, "online": False, "error": "Invalid peer URL", "failure_count": failure_count, "reputation": get_peer_reputation(peer)})
            continue
        try:
            response = signed_get(f"{peer_url}/node_info", path="/node_info", timeout=3)
            latency_ms = round((time.time() - started) * 1000, 2)
            response.raise_for_status()
            info = response.json()
            results.append({
                "peer": peer,
                "online": True,
                "latency_ms": latency_ms,
                "height": info.get("height"),
                "valid": info.get("valid"),
                "node_id": info.get("node_id"),
                "failure_count": failure_count,
                "reputation": get_peer_reputation(peer),
            })
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            results.append({"peer": peer, "online": False, "error": str(exc), "failure_count": failure_count, "reputation": get_peer_reputation(peer)})
    return results


def get_self_peer_url():
    config = read_json("node_config.json", {})
    host = config.get("host", "127.0.0.1")
    port = int(config.get("port", 5000))
    # Normalize the host:port via normalize_peer so addresses like 0.0.0.0
    # are canonicalized to 127.0.0.1 and the scheme matches chain config.
    normalized = normalize_peer(f"{host}:{port}")
    return normalized


def is_self_peer(peer):
    normalized = normalize_peer(peer)
    if not normalized:
        return False
    return normalized.rstrip("/") == get_self_peer_url().rstrip("/")


def get_network_id():
    return load_chain_config().get("network_id")


def get_peer_registration_token():
    return load_chain_config().get("peer_registration_token")


def is_peer_registration_authorized(data):
    required_token = get_peer_registration_token()
    if not required_token:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth_header = auth_header[len("Bearer "):].strip()
    token = data.get("auth_token") or auth_header
    return token == required_token


def peer_node_info(peer, allow_blacklisted=False):
    cleanup_blacklist()
    peer_url = normalize_peer(peer)
    if not peer_url or is_self_peer(peer_url) or (not allow_blacklisted and is_peer_blacklisted(peer_url)):
        return None
    try:
        response = signed_get(f"{peer_url}/node_info", path="/node_info", timeout=3)
        response.raise_for_status()
        info = response.json()
        if not info.get("valid"):
            blacklist_peer(peer_url, "Invalid node info")
            return None
        if info.get("network_id") != get_network_id():
            blacklist_peer(peer_url, "Network mismatch")
            return None
        stored = get_stored_peer(peer_url)
        failures = load_peer_failures()
        if stored in failures:
            failures.pop(stored, None)
            save_peer_failures(failures)
        update_peer_reputation(peer_url, 5, reason="healthy node")
        info["peer"] = peer
        info["url"] = peer_url
        return info
    except Exception as exc:
        record_peer_failure(peer_url, str(exc))
        return None


def healthy_peers():
    ranked = []
    for peer in load_peers():
        info = peer_node_info(peer)
        if info:
            reputation = get_peer_reputation(peer)
            score = reputation.get("score", 0)
            info["reputation_score"] = score
            ranked.append((score, info))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked]


def sync_peer_list():
    peers = load_peers()
    self_url = get_self_peer_url()
    added = 0
    errors = []
    for peer in list(peers):
        peer_url = normalize_peer(peer)
        if (
            not peer_url
            or peer_url.rstrip("/") == self_url.rstrip("/")
            or is_peer_blacklisted(peer_url)
        ):
            continue
        remote_info = peer_node_info(peer_url)
        if not remote_info:
            continue
        try:
            response = signed_get(f"{peer_url}/peers", path="/peers", timeout=5)
            response.raise_for_status()
            for remote in response.json():
                normalized = normalize_peer(remote)
                if not normalized or normalized.rstrip("/") == self_url.rstrip("/"):
                    continue
                if is_peer_blacklisted(normalized):
                    continue
                stored = normalized.replace("http://", "").replace("https://", "")
                if stored not in peers:
                    peers.append(stored)
                    added += 1
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            errors.append({"peer": peer, "error": str(exc)})
        if added:
            write_json(PEERS_FILE, peers)
    if added:
        write_json(PEERS_FILE, peers)
    sync_public_keys()
    sync_wallets()
    return peers, added, errors


def get_bootstrap_policy():
    security_config = load_chain_config().get("security", {})
    trust_policy = load_chain_config().get("peer_trust_policy", {})
    return {
        "peer_auth_required": bool(security_config.get("peer_shared_secret")),
        "peer_registration_token_required": bool(load_chain_config().get("peer_registration_token")),
        "tls_required": bool(security_config.get("tls_enabled", False)),
        "rate_limit": security_config.get("rate_limit", 120),
        "allow_public_bootstrap": bool(trust_policy.get("allow_public_bootstrap", True)),
        "allowlist": trust_policy.get("allowlist", []),
        "denylist": trust_policy.get("denylist", []),
    }


def is_peer_trusted(peer):
    trust_policy = load_chain_config().get("peer_trust_policy", {})
    if not isinstance(trust_policy, dict):
        return True
    peer_value = str(peer).strip().rstrip("/")
    allowlist = trust_policy.get("allowlist", []) or []
    denylist = trust_policy.get("denylist", []) or []
    if peer_value in denylist:
        return False
    if allowlist:
        return peer_value in allowlist
    return bool(trust_policy.get("allow_public_bootstrap", True))


def bootstrap():
    config = load_chain_config()
    seed_nodes = config.get("seed_nodes", [])
    peers = load_peers()
    self_url = get_self_peer_url()
    added = 0
    for seed in seed_nodes:
        normalized = normalize_peer(seed)
        if not normalized or normalized.rstrip("/") == self_url.rstrip("/"):
            continue
        stored = normalized.replace("http://", "").replace("https://", "")
        if stored not in peers:
            peers.append(stored)
            added += 1
    if added:
        write_json(PEERS_FILE, peers)
    discovered_peers, discovered_added, errors = sync_peer_list()
    public_key_sync = sync_public_keys()
    wallet_sync = sync_wallets()
    bootstrap_state = {
        "last_bootstrap_status": "complete",
        "last_bootstrap_timestamp": time.time(),
        "seed_added": added,
        "discovered_peer_added": discovered_added,
        "peer_count": len(discovered_peers),
        "errors": errors,
        "public_keys_synced": public_key_sync.get("updated", False),
        "public_key_count": public_key_sync.get("count", 0),
        "wallets_synced": wallet_sync.get("updated", False),
        "wallet_count": wallet_sync.get("count", 0),
    }
    config["bootstrap_state"] = bootstrap_state
    write_json(CHAIN_CONFIG_FILE, config)
    append_node_event("bootstrap", "Bootstrap completed", bootstrap_state)
    return {
        "message": "Bootstrap complete",
        "seed_added": added,
        "discovered_peer_added": discovered_added,
        "errors": errors,
        "peers": discovered_peers,
        "node_version": "kwd-node-1.2.0",
        "bootstrap_policy": get_bootstrap_policy(),
        "bootstrap_authenticated": bool(load_chain_config().get("security", {}).get("peer_shared_secret")),
        "monitoring_enabled": bool(load_chain_config().get("security", {}).get("monitoring_enabled", True)),
    }


def _invoke_sync_chain():
    sync_impl = globals().get("sync_chain")
    if callable(sync_impl):
        return sync_impl()
    return sync_chain()


def _attempt_startup_sync(max_attempts=3, delay_seconds=1.0):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _invoke_sync_chain()
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(result["error"])
            return result
        except Exception as exc:
            last_error = str(exc)
            print(f"Post-bootstrap sync attempt {attempt}/{max_attempts} failed: {exc}")
            if attempt < max_attempts:
                time.sleep(delay_seconds)
    return {"error": last_error or "startup sync failed"}


def bootstrap_on_startup(force=False):
    config = load_chain_config()
    seed_nodes = config.get("seed_nodes", []) or []
    if not seed_nodes:
        return {"message": "No seed nodes configured", "skipped": True}

    state = config.get("bootstrap_state", {}) or {}
    last_bootstrap = state.get("last_bootstrap_timestamp", 0)
    if not force and last_bootstrap and (time.time() - float(last_bootstrap)) < 300:
        sync_result = _attempt_startup_sync()
        return {
            "message": "Bootstrap already completed recently",
            "skipped": True,
            "peers": load_peers(),
            "sync": sync_result,
        }

    bootstrap_result = bootstrap()
    bootstrap_result["sync"] = _attempt_startup_sync()
    return bootstrap_result


def sync_public_keys():
    registry = read_json(PUBLIC_KEYS_FILE, [])
    if not isinstance(registry, list):
        registry = []
    existing = {item.get("address"): item for item in registry if item.get("address")}
    updated = False
    for peer in load_peers():
        peer_url = normalize_peer(peer)
        if not peer_url or is_self_peer(peer_url):
            continue
        try:
            response = signed_get(f"{peer_url}/public_keys", path="/public_keys", timeout=3)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("public_keys", payload.get("keys", []))
            if not isinstance(payload, list):
                continue
            for item in payload:
                address = item.get("address") if isinstance(item, dict) else None
                public_key = item.get("public_key") if isinstance(item, dict) else None
                if not address or not public_key:
                    continue
                if address not in existing:
                    existing[address] = {"address": address, "public_key": public_key}
                    updated = True
        except Exception:
            continue
    if updated:
        registry = list(existing.values())
        write_json(PUBLIC_KEYS_FILE, registry)
    return {"updated": updated, "count": len(existing)}


def sync_wallets():
    registry = read_json(WALLETS_FILE, [])
    if not isinstance(registry, list):
        registry = []
    existing = {item.get("address") or item.get("wallet"): item for item in registry if isinstance(item, dict) and (item.get("address") or item.get("wallet"))}
    updated = False
    for peer in load_peers():
        peer_url = normalize_peer(peer)
        if not peer_url or is_self_peer(peer_url):
            continue
        try:
            response = signed_get(f"{peer_url}/wallet_registry", path="/wallet_registry", timeout=3)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("wallets", payload.get("wallet_registry", payload.get("records", [])))
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                address = item.get("address") or item.get("wallet")
                if not address:
                    continue
                before = dict(existing.get(address, {})) if address in existing else None
                normalized = {
                    "wallet": item.get("wallet") or address,
                    "address": address,
                    "public_key": item.get("public_key"),
                }
                metadata = item.get("metadata")
                if isinstance(metadata, dict):
                    normalized["metadata"] = dict(metadata)
                elif metadata is not None:
                    normalized["metadata"] = metadata
                if address in existing:
                    current = dict(existing[address])
                    current.setdefault("wallet", normalized.get("wallet", address))
                    current.setdefault("address", address)
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
                    existing[address] = current
                else:
                    existing[address] = normalized
                    updated = True
                if before is None or dict(existing[address]) != before:
                    updated = True
        except Exception:
            continue
    if updated:
        write_json(WALLETS_FILE, list(existing.values()))
    return {"updated": updated, "count": len(existing)}


def wallet_summary(address, chain):
    balance = 0
    received = 0
    sent = 0
    tx_count = 0
    for _block, _tx_data, tx in iter_transactions(chain):
        if tx.get("to") == address:
            received += tx["amount"]
            balance += tx["amount"]
            tx_count += 1
        if tx.get("from") == address:
            spend = tx["amount"] + tx.get("fee", 0)
            sent += spend
            balance -= spend
            tx_count += 1
    return {
        "address": address,
        "balance": balance,
        "received": received,
        "sent": sent,
        "transactions": tx_count,
    }


@app.route("/")
def home():
    return "KWD Blockchain API Running"


@app.route("/chain")
def get_chain():
    chain = load_chain()
    valid, error = validate_chain_data(chain)
    return jsonify({"length": len(chain), "valid": valid, "error": error, "chain": chain})


@app.route("/node_info")
def node_info():
    chain = load_chain()
    valid, error = validate_chain_data(chain)
    latest = chain[-1] if chain else {}
    config = read_json("node_config.json", {})
    chain_config_data = load_chain_config()
    return {
        "node_id": config.get("node_id", f"kwd-node-{config.get('port', 'unknown')}"),
        "node_version": "kwd-node-1.2.0",
        "network_name": chain_config_data.get("network_name"),
        "ticker": chain_config_data.get("ticker"),
        "network_id": chain_config_data.get("network_id"),
        "port": config.get("port"),
        "height": len(chain),
        "chain_work": chain_work(chain),
        "latest_hash": latest.get("hash"),
        "difficulty": latest.get("difficulty", 0),
        "next_difficulty": calculate_next_difficulty(chain),
        "valid": valid,
        "error": error,
        "mempool": len(load_mempool()),
        "orphans": len(load_orphans()),
        "peers": len(load_peers()),
        "supply": get_total_supply(chain),
    }


@app.route("/consensus")
def consensus():
    chain = load_chain()
    config = load_chain_config()
    return {
        "network_name": config.get("network_name"),
        "ticker": config.get("ticker"),
        "network_id": config.get("network_id"),
        "target_block_time_seconds": config.get("target_block_time", TARGET_BLOCK_TIME),
        "difficulty_adjustment_interval": config.get(
            "difficulty_adjustment_interval",
            DIFFICULTY_ADJUSTMENT_INTERVAL,
        ),
        "max_future_block_time_seconds": config.get(
            "max_future_block_time",
            MAX_FUTURE_BLOCK_TIME,
        ),
        "min_difficulty": config.get("min_difficulty", MIN_DIFFICULTY),
        "max_difficulty": config.get("max_difficulty", MAX_DIFFICULTY),
        "max_supply": config.get("max_supply"),
        "initial_reward": config.get("initial_reward"),
        "reward_schedule": config.get("reward_schedule", []),
        "next_difficulty": calculate_next_difficulty(chain),
    }


@app.route("/chain_config")
def chain_config():
    return load_chain_config()


@app.route("/validate")
def validate_chain():
    chain = load_chain()
    valid, error = validate_chain_data(chain)
    return {"valid": valid, "error": error}


@app.route("/reset_chain", methods=["POST"])
def reset_chain_route():
    chain, backup_path = reset_chain()
    return {
        "message": "Chain reset to clean genesis block",
        "backup": backup_path,
        "blocks": len(chain),
    }


@app.route("/public_keys")
def public_keys():
    return read_json(PUBLIC_KEYS_FILE, [])


@app.route("/wallet_registry")
def wallet_registry():
    return read_json(WALLETS_FILE, [])


@app.route("/register_public_key", methods=["POST"])
def register_public_key_route():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Request body must be a JSON object"}, 400
    address = data.get("address")
    public_key = data.get("public_key")
    if not address or not public_key:
        return {"error": "Missing address or public_key"}, 400
    register_public_key(address, public_key)
    return {"message": "Public key registered", "address": address}


@app.route("/register_wallet", methods=["POST"])
def register_wallet_route():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Request body must be a JSON object"}, 400
    address = data.get("address") or data.get("wallet")
    public_key = data.get("public_key")
    if not address:
        return {"error": "Missing address or wallet"}, 400
    register_wallet(address=address, public_key=public_key, wallet=data.get("wallet") or address, metadata=data.get("metadata"))
    return {"message": "Wallet registered", "address": address}


@app.route("/balance/<wallet>")
def balance(wallet):
    return {"wallet": wallet, "balance": get_balance(wallet, load_chain())}


@app.route("/transactions/<wallet>")
@app.route("/history/<wallet>")
def transactions(wallet):
    result = []
    for block, tx_data, tx in iter_transactions(load_chain()):
        if tx.get("from") == wallet or tx.get("to") == wallet:
            item = dict(tx)
            item["block"] = block["index"]
            item["txid"] = tx.get("txid") or tx_id(tx_data)
            result.append(item)
    return result


@app.route("/wallet/<address>/transactions")
def wallet_transactions(address):
    page = request.args.get("page", 1)
    try:
        page = int(page)
    except (TypeError, ValueError):
        return {"error": "Invalid page"}, 400
    page = max(1, page)
    result = []
    for block, tx_data, tx in iter_transactions(load_chain()):
        if tx.get("from") == address or tx.get("to") == address:
            item = dict(tx)
            item["block"] = block["index"]
            item["txid"] = tx.get("txid") or tx_id(tx_data)
            result.append(item)
    page_size = 25
    start = (page - 1) * page_size
    end = start + page_size
    return result[start:end]


@app.route("/block/<int:index>")
def get_block(index):
    for block in load_chain():
        if block.get("index") == index:
            return block
    return {"error": "Block not found"}, 404


@app.route("/export/block/<int:index>")
def export_block(index):
    for block in load_chain():
        if block.get("index") == index:
            return {
                "block": block,
                "height": index,
                "exported_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            }
    return {"error": "Block not found"}, 404


@app.route("/block/<int:index>/header")
def get_block_header(index):
    for block in load_chain():
        if block.get("index") == index:
            return {
                "index": block.get("index"),
                "timestamp": block.get("timestamp"),
                "proof": block.get("proof"),
                "difficulty": block.get("difficulty"),
                "previous_hash": block.get("previous_hash"),
                "hash": block.get("hash"),
            }
    return {"error": "Block not found"}, 404


@app.route("/block/<int:index>/transactions")
def get_block_transactions(index):
    for block in load_chain():
        if block.get("index") == index:
            return block.get("transactions", [])
    return {"error": "Block not found"}, 404


@app.route("/block/<int:index>/fees")
def get_block_fees(index):
    for block in load_chain():
        if block.get("index") == index:
            total_fees = 0.0
            for tx_data in block.get("transactions", []):
                tx = tx_payload(tx_data)
                fee = None
                if isinstance(tx, dict):
                    fee = tx.get("fee") if tx.get("fee") is not None else tx.get("fees")
                try:
                    total_fees += float(fee)
                except (TypeError, ValueError):
                    continue
            return {"index": index, "fees": total_fees}
    return {"error": "Block not found"}, 404


@app.route("/block/<int:index>/reward")
def get_block_reward(index):
    for block in load_chain():
        if block.get("index") == index:
            for tx_data in block.get("transactions", []):
                if tx_signature(tx_data) == MINING_REWARD_SIGNATURE:
                    tx = tx_payload(tx_data)
                    base_reward = tx.get("base_reward", tx.get("amount", 0))
                    fees = tx.get("fees", 0)
                    total_reward = tx.get("amount", base_reward + fees)
                    return {
                        "index": index,
                        "base_reward": base_reward,
                        "fees": fees,
                        "total_reward": total_reward,
                        "to": tx.get("to"),
                        "txid": tx.get("txid"),
                    }
            return {"index": index, "base_reward": 0.0, "fees": 0.0, "total_reward": 0.0}
    return {"error": "Block not found"}, 404


@app.route("/block/hash/<hash>")
def get_block_by_hash(hash):
    for block in load_chain():
        if block.get("hash") == hash:
            return block
    return {"error": "Block not found"}, 404


@app.route("/block/<int:index>/prev")
def prev_block(index):
    return redirect(f"/block/{max(1, index - 1)}")


@app.route("/block/<int:index>/next")
def next_block(index):
    return redirect(f"/block/{index + 1}")


@app.route("/latest_block")
def latest_block():
    chain = load_chain()
    if not chain:
        return {"error": "Chain is empty"}, 404
    return chain[-1]


@app.route("/mempool")
@app.route("/pending")
def mempool():
    return load_mempool()


@app.route("/mempool_stats")
def mempool_stats():
    mempool_data = load_mempool()
    return {
        "transactions": len(mempool_data),
        "pending_fees": get_pending_fee_total(mempool_data),
    }


@app.route("/orphan_blocks")
def orphan_blocks():
    return load_orphans()


@app.route("/process_orphans")
def process_orphans():
    cleanup = cleanup_orphans()
    return {
        "attached": cleanup["attached"],
        "removed_stale": cleanup["removed_stale"],
        "remaining": len(load_orphans()),
        "height": len(load_chain()),
    }


@app.route("/create_transaction", methods=["POST"])
def create_transaction():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Transaction payload must be an object"}, 400
    chain = load_chain()
    mempool_data = load_mempool() or []
    valid, error = validate_transaction(data, chain, mempool_data)
    if not valid:
        return {"error": error}, 400
    current_txid = tx_id(data)
    duplicate_error = transaction_duplicate_error(data, chain, mempool_data)
    if duplicate_error:
        return {"error": duplicate_error}, 409
    mempool_data.append(data)
    try:
        save_mempool(mempool_data, reason="new transaction")
    except OSError as exc:
        return {"error": f"Could not persist mempool: {exc}"}, 500
    broadcast_transaction(data)
    return {"message": "Transaction added to mempool", "txid": current_txid}


@app.route("/send_transaction", methods=["POST"])
def send_transaction():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Request body must be a JSON object"}, 400
    required = ("private_key", "to", "amount")
    missing = [field for field in required if field not in data]
    if missing:
        return {"error": f"Missing fields: {', '.join(missing)}"}, 400
    chain = load_chain()
    mempool_data = load_mempool()
    try:
        signed_tx = create_signed_transaction(
            data["private_key"],
            data["to"],
            data["amount"],
            fee=data.get("fee"),
            nonce=data.get("nonce"),
            chain=chain,
            mempool=mempool_data,
        )
    except Exception as exc:
        return {"error": f"Could not sign transaction: {exc}"}, 400
    valid, error = validate_transaction(signed_tx, chain, mempool_data)
    if not valid:
        return {"error": error, "transaction": signed_tx}, 400
    duplicate_error = transaction_duplicate_error(signed_tx, chain, mempool_data)
    if duplicate_error:
        return {"error": duplicate_error}, 409
    mempool_data.append(signed_tx)
    try:
        save_mempool(mempool_data, reason="new signed transaction")
    except OSError as exc:
        return {"error": f"Could not persist mempool: {exc}"}, 500
    broadcast_transaction(signed_tx)
    return {
        "message": "Transaction signed and added to mempool",
        "txid": tx_id(signed_tx),
        "transaction": signed_tx,
    }


@app.route("/receive_transaction", methods=["POST"])
def receive_transaction():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Transaction payload must be an object"}, 400
    chain = load_chain()
    mempool_data = load_mempool() or []
    valid, error = validate_transaction(data, chain, mempool_data)
    if not valid:
        return {"error": error}, 400
    current_txid = tx_id(data)
    duplicate_error = transaction_duplicate_error(data, chain, mempool_data)
    if duplicate_error:
        return {"message": duplicate_error, "txid": current_txid}, 409
    mempool_data.append(data)
    try:
        save_mempool(mempool_data, reason="received transaction")
    except OSError as exc:
        return {"error": f"Could not persist mempool: {exc}"}, 500
    return {"message": "Transaction received", "txid": current_txid}


@app.route("/receive_block", methods=["POST"])
def receive_block():
    new_block = request.get_json(silent=True) or {}
    chain = load_chain()
    previous = chain[-1] if chain else None
    candidate_valid, candidate_error = validate_candidate_block(
        new_block,
        check_future_time=True,
        prefix="Received block",
        prior_chain=chain,
    )
    if not candidate_valid:
        return {"error": candidate_error}, 400
    if previous and new_block.get("previous_hash") != previous.get("hash"):
        stored = save_orphan_block(
            new_block,
            "Previous hash does not match current tip",
        )
        return {
            "message": "Block stored as orphan",
            "hash": new_block.get("hash"),
            "previous_hash": new_block.get("previous_hash"),
            "current_tip": previous.get("hash") if previous else None,
            "orphan": stored,
        }, 202
    valid, error = validate_block(
        new_block,
        previous_block=previous,
        full_transactions=True,
        prior_chain=chain,
        check_future_time=True,
        prefix="Received block",
    )
    if not valid:
        return {"error": error}, 400
    candidate_chain = chain + [new_block]
    valid, error = validate_chain_data(candidate_chain)
    if not valid:
        return {"error": error}, 400
    chain.append(new_block)
    write_json(CHAIN_FILE, chain)
    remove_mined_transactions(new_block)
    removed_mempool = reconcile_mempool(chain)
    orphan_cleanup = cleanup_orphans()
    return {
        "message": "Block received",
        "index": new_block["index"],
        "orphan_cleanup": orphan_cleanup,
        "removed_mempool": removed_mempool,
    }


@app.route("/mine")
def mine():
    try:
        sync_chain()
    except Exception as exc:
        print(f"Peer sync before mining failed: {exc}")

    result = subprocess.run(
        [sys.executable, "mine_block.py"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    if result.returncode != 0:
        return {"error": "Mining failed", "details": result.stderr or result.stdout}, 500
    chain = load_chain()
    if chain:
        remove_mined_transactions(chain[-1])
        broadcast_block(chain[-1])
    return {"message": "Block mined and broadcasted", "details": result.stdout}

@app.route("/sync_chain")
def sync_chain():
    sync_peer_list()
    cleanup_orphans()
    peers_to_query = []
    for peer in load_peers(allow_blacklisted=True):
        peer_url = normalize_peer(peer)
        if not peer_url:
            continue
        if peer_url.rstrip("/") == get_self_peer_url().rstrip("/"):
            continue
        peers_to_query.append(peer)
    current_chain = load_chain()
    current_length = len(current_chain)
    current_work = chain_work(current_chain)
    print(f"[sync_chain] local_length={current_length} local_work={current_work}")

    best_chain = current_chain
    best_source = None
    best_length = current_length
    best_work = current_work
    best_reason = "local chain retained"
    errors = []

    for peer in peers_to_query:
        peer_url = normalize_peer(peer)
        if not peer_url:
            continue
        try:
            response = signed_get(f"{peer_url}/chain", path="/chain", timeout=5)
            status_code = getattr(response, "status_code", None)
            response.raise_for_status()
            payload = response.json()
            peer_chain = payload.get("chain", []) if isinstance(payload, dict) else payload
            if not isinstance(peer_chain, list):
                raise ValueError("Peer response did not contain a chain list")
            valid, error = validate_chain_data(peer_chain)
            peer_length = len(peer_chain)
            peer_work = chain_work(peer_chain)
            rejection_reason = error if not valid else "valid"
            print(
                f"[sync_chain] peer={peer} url={peer_url} status={status_code} "
                f"downloaded_length={peer_length} downloaded_work={peer_work} "
                f"validation_passed={valid} reason={rejection_reason}"
            )
            if not valid:
                errors.append({"peer": peer, "error": error or "Invalid chain", "reason": rejection_reason})
                continue
            if peer_length > best_length or (peer_length == best_length and peer_work > best_work):
                best_chain = peer_chain
                best_source = peer
                best_length = peer_length
                best_work = peer_work
                best_reason = f"peer chain surpassed local chain at length={peer_length} work={peer_work}"
                print(
                    f"[sync_chain] candidate_selected peer={peer} url={peer_url} "
                    f"downloaded_length={peer_length} downloaded_work={peer_work}"
                )
            else:
                print(
                    f"[sync_chain] peer={peer} rejected because downloaded_length={peer_length} "
                    f"downloaded_work={peer_work} did not exceed current best length={best_length} work={best_work}"
                )
        except requests.Timeout as exc:
            record_peer_failure(peer_url, str(exc))
            errors.append({"peer": peer, "error": str(exc), "reason": "request timed out"})
            print(f"[sync_chain] peer={peer} url={peer_url} status=timeout reason=request timed out error={exc}")
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            errors.append({"peer": peer, "error": str(exc), "reason": "request failed"})
            print(f"[sync_chain] peer={peer} url={peer_url} status=error reason=request failed error={exc}")

    replaced = False
    if best_source is not None and (best_length > current_length or (best_length == current_length and best_work > current_work)):
        backup_path = backup_file(CHAIN_FILE)
        write_json(CHAIN_FILE, best_chain)
        removed_mempool = reconcile_mempool(best_chain)
        attached_orphans = attach_connectable_orphans(best_chain)
        if attached_orphans:
            write_json(CHAIN_FILE, best_chain)
        replaced = True
        print(
            f"[sync_chain] selected_peer={best_source} local_length={current_length} "
            f"peer_length={best_length} replacement=True final_length={len(best_chain)} reason={best_reason}"
        )
        return {
            "message": "Chain replaced with stronger valid chain",
            "source": best_source,
            "blocks": len(best_chain),
            "chain_work": best_work,
            "backup": backup_path,
            "removed_mempool": removed_mempool,
            "attached_orphans": attached_orphans,
            "peer_errors": errors,
            "replacement": replaced,
            "selected_peer": best_source,
            "local_length": current_length,
            "peer_length": best_length,
        }

    if not peers_to_query:
        selection_reason = "no peers were available to query"
    elif not any(item.get("error") is None for item in errors):
        selection_reason = "all peer responses failed or were rejected"
    else:
        selection_reason = "no valid peer chain was longer or stronger than the local chain"
    print(
        f"[sync_chain] selected_peer=None local_length={current_length} "
        f"peer_length={best_length} replacement=False final_length={len(current_chain)} reason={selection_reason}"
    )
    return {
        "message": "Already on the strongest valid chain",
        "blocks": len(current_chain),
        "chain_work": current_work,
        "peer_errors": errors,
        "replacement": replaced,
        "selected_peer": None,
        "local_length": current_length,
        "peer_length": best_length,
        "selection_reason": selection_reason,
    }

@app.route("/bootstrap")
def bootstrap_route():
    return bootstrap()


@app.route("/bootstrap_status")
def bootstrap_status():
    config = load_chain_config()
    return {
        "status": "ok",
        "seed_nodes": config.get("seed_nodes", []),
        "bootstrap_state": config.get("bootstrap_state", {}),
        "bootstrap_policy": get_bootstrap_policy(),
    }


@app.route("/backup_state", methods=["POST"])
def backup_state():
    data = request.get_json(silent=True) or {}
    target = data.get("path") or CHAIN_FILE
    backup_path = backup_file(target)
    append_audit_event("backup_state", "State backup created", {"path": target, "backup_path": backup_path})
    return {
        "message": "State backup created",
        "path": target,
        "backup_path": backup_path,
        "created": backup_path is not None,
    }


@app.route("/backup_status")
def backup_status():
    config = load_chain_config()
    backup_files = sorted(
        [name for name in os.listdir('.') if name.startswith("blockchain_data.json.backup-")],
        reverse=True,
    )
    return {
        "status": "ok",
        "latest_backup": backup_files[0] if backup_files else None,
        "backup_count": len(backup_files),
        "recovery_mode": bool(config.get("security", {}).get("recovery_mode", False)),
    }


@app.route("/restore_state", methods=["POST"])
def restore_state():
    data = request.get_json(silent=True) or {}
    target = data.get("path", CHAIN_FILE)
    default = data.get("default")
    recovered = recover_state_file(target, default=default)
    append_audit_event("restore_state", "State recovery attempted", {"path": target})
    return {
        "message": "State recovery attempted",
        "path": target,
        "recovered": recovered is not None,
        "value": recovered,
    }


@app.route("/bootstrap_config", methods=["POST"])
def bootstrap_config():
    data = request.get_json(silent=True) or {}
    config = load_chain_config()
    if "seed_nodes" in data:
        config["seed_nodes"] = data.get("seed_nodes", [])
    if "trust_policy" in data:
        config["peer_trust_policy"] = data.get("trust_policy", {})
    config.setdefault("security", {})["rollout_pending"] = bool(data.get("rollout_pending", False))
    config.setdefault("security", {})["rollout_safety_mode"] = bool(data.get("rollout_safety_mode", False))
    config.setdefault("security", {})["public_api_enabled"] = bool(data.get("public_api_enabled", True))
    write_json(CHAIN_CONFIG_FILE, config)
    append_audit_event("bootstrap_config", "Bootstrap configuration updated", {"seed_nodes": config.get("seed_nodes", [])})
    append_approval_event("bootstrap_config", True, {"seed_nodes": config.get("seed_nodes", [])})
    return {
        "message": "Bootstrap configuration updated",
        "seed_nodes": config.get("seed_nodes", []),
        "trust_policy": config.get("peer_trust_policy", {}),
        "rollout_state": {
            "rollout_pending": config.get("security", {}).get("rollout_pending", False),
            "rollout_safety_mode": config.get("security", {}).get("rollout_safety_mode", False),
            "public_api_enabled": config.get("security", {}).get("public_api_enabled", True),
        },
    }


@app.route("/trust_policy_update", methods=["POST"])
def trust_policy_update():
    if not is_admin_authorized():
        append_audit_event("trust_policy_update_denied", "Admin authentication missing", {})
        return {"error": "Admin authentication required"}, 403
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    config = load_chain_config()
    trust_policy = config.setdefault("peer_trust_policy", {})
    if action == "promote_by_reputation":
        threshold = data.get("threshold", 10)
        promoted = []
        for peer in load_peers():
            reputation = get_peer_reputation(peer)
            score = reputation.get("score", 0)
            if score >= threshold:
                allowlist = trust_policy.setdefault("allowlist", [])
                stored = get_stored_peer(peer)
                if stored and stored not in allowlist:
                    allowlist.append(stored)
                    promoted.append(stored)
        write_json(CHAIN_CONFIG_FILE, config)
        append_audit_event("trust_policy_update", "Promoted peers by reputation", {"threshold": threshold, "promoted": promoted})
        append_approval_event("trust_policy_update", True, {"action": "promote_by_reputation", "count": len(promoted)})
        return {"status": "ok", "action": "promote_by_reputation", "promoted": promoted}
    if action == "demote_by_reputation":
        threshold = data.get("threshold", -5)
        demoted = []
        for peer in load_peers():
            reputation = get_peer_reputation(peer)
            score = reputation.get("score", 0)
            if score <= threshold:
                denylist = trust_policy.setdefault("denylist", [])
                stored = get_stored_peer(peer)
                if stored and stored not in denylist:
                    denylist.append(stored)
                    demoted.append(stored)
        write_json(CHAIN_CONFIG_FILE, config)
        append_audit_event("trust_policy_update", "Demoted peers by reputation", {"threshold": threshold, "demoted": demoted})
        append_approval_event("trust_policy_update", True, {"action": "demote_by_reputation", "count": len(demoted)})
        return {"status": "ok", "action": "demote_by_reputation", "demoted": demoted}
    append_audit_event("trust_policy_update", "Unsupported action", {"action": action})
    return {"error": "Unsupported action"}, 400


@app.route("/deployment_control", methods=["POST"])
def deployment_control():
    if not is_admin_authorized():
        append_audit_event("deployment_control_denied", "Admin authentication missing", {"path": request.path})
        return {"error": "Admin authentication required"}, 403
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    config = load_chain_config()
    if action == "set":
        key = data.get("key")
        value = data.get("value")
        if not key:
            return {"error": "Missing key"}, 400
        if key == "security":
            config["security"] = value or {}
        elif key.startswith("security."):
            sec_key = key.split(".", 1)[1]
            config.setdefault("security", {})[sec_key] = value
        elif key in {"rate_limit", "rate_limit_window_seconds", "rate_limit_ban_seconds", "peer_shared_secret", "tls_enabled", "tls_cert_path", "tls_key_path", "monitoring_enabled", "encrypt_private_keys", "public_api_enabled", "rollout_safety_mode", "rollout_pending"}:
            config.setdefault("security", {})[key] = value
        else:
            config[key] = value
        write_json(CHAIN_CONFIG_FILE, config)
        append_audit_event("deployment_control", "Configuration changed", {"key": key, "value": value})
        append_approval_event("deployment_control", True, {"key": key, "value": value})
        return {"status": "ok", "key": key, "value": value}
    if action == "get":
        key = data.get("key")
        return {"status": "ok", "key": key, "value": config.get(key) if not key.startswith("security.") else config.get("security", {}).get(key.split(".", 1)[1])}
    append_audit_event("deployment_control", "Unsupported action", {"action": action})
    return {"error": "Unsupported action"}, 400


@app.route("/deployment_status")
def deployment_status():
    config = load_chain_config()
    security_config = config.get("security", {})
    return {
        "status": "ok",
        "node_version": "kwd-node-1.2.0",
        "network_id": config.get("network_id"),
        "seed_nodes": config.get("seed_nodes", []),
        "peer_trust_policy": config.get("peer_trust_policy", {}),
        "security": security_config,
        "rollout_state": {
            "rollout_pending": bool(security_config.get("rollout_pending", False)),
            "rollout_safety_mode": bool(security_config.get("rollout_safety_mode", False)),
            "public_api_enabled": bool(security_config.get("public_api_enabled", True)),
        },
    }


@app.route("/launch_readiness")
def launch_readiness():
    config = load_chain_config()
    security_config = config.get("security", {})
    chain = load_chain()
    peers_data = healthy_peers()
    seed_nodes = config.get("seed_nodes", [])
    trust_policy = config.get("peer_trust_policy", {})
    checks = {
        "chain_initialized": len(chain) >= 1,
        "genesis_block_valid": len(chain) > 0 and chain[0].get("index") in (0, 1),
        "tls_enabled": bool(security_config.get("tls_enabled", False)),
        "rate_limiting_enabled": bool(security_config.get("rate_limit", 0) > 0),
        "monitoring_enabled": bool(security_config.get("monitoring_enabled", False)),
        "seed_nodes_configured": len(seed_nodes) > 0,
        "trust_policy_configured": bool(trust_policy),
        "healthy_peers_available": len(peers_data) > 0,
        "rollout_safety_disabled": not bool(security_config.get("rollout_safety_mode", False)),
        "public_api_enabled": bool(security_config.get("public_api_enabled", True)),
    }
    all_ready = all(checks.values())
    return {
        "status": "ok",
        "ready_for_launch": all_ready,
        "readiness_checks": checks,
        "healthy_peers_count": len(peers_data),
        "seed_nodes_count": len(seed_nodes),
        "chain_height": len(chain),
        "timestamp": time.time(),
    }


@app.route("/deployment_runbook")
def deployment_runbook():
    config = load_chain_config()
    network_id = config.get("network_id", "kwd-testnet-local")
    seed_nodes = config.get("seed_nodes", [])
    return {
        "status": "ok",
        "version": "1.0",
        "network_id": network_id,
        "steps": [
            {
                "step": 1,
                "title": "Pre-Launch Verification",
                "description": "Verify all nodes pass launch readiness checks",
                "endpoint": "/launch_readiness",
                "expected": "ready_for_launch: true",
                "command": f"curl http://localhost:5000/launch_readiness",
            },
            {
                "step": 2,
                "title": "Enable Public API",
                "description": "Enable public API access for external nodes",
                "endpoint": "/deployment_control",
                "command": f'curl -X POST http://localhost:5000/deployment_control -H "Authorization: Bearer <ADMIN_TOKEN>" -H "Content-Type: application/json" -d \'{{"action": "set", "key": "public_api_enabled", "value": true}}\'',
            },
            {
                "step": 3,
                "title": "Disable Safety Mode",
                "description": "Disable rollout safety mode to allow normal operations",
                "endpoint": "/deployment_control",
                "command": f'curl -X POST http://localhost:5000/deployment_control -H "Authorization: Bearer <ADMIN_TOKEN>" -H "Content-Type: application/json" -d \'{{"action": "set", "key": "rollout_safety_mode", "value": false}}\'',
            },
            {
                "step": 4,
                "title": "Configure Seed Nodes",
                "description": f"Configure seed nodes for peer discovery. Current: {seed_nodes}",
                "endpoint": "/bootstrap_config",
                "command": f'curl -X POST http://localhost:5000/bootstrap_config -H "Authorization: Bearer <ADMIN_TOKEN>" -H "Content-Type: application/json" -d \'{{"seed_nodes": ["<SEED_NODE_1>", "<SEED_NODE_2>"]}}\'' ,
            },
            {
                "step": 5,
                "title": "Initiate Bootstrap",
                "description": "Start peer discovery and blockchain synchronization",
                "endpoint": "/bootstrap",
                "command": f"curl -X POST http://localhost:5000/bootstrap",
            },
            {
                "step": 6,
                "title": "Monitor Network Health",
                "description": "Verify peer connectivity and network health",
                "endpoint": "/network_health_dashboard",
                "command": f"curl http://localhost:5000/network_health_dashboard",
            },
            {
                "step": 7,
                "title": "Launch Complete",
                "description": "Public testnet is now live",
                "verification": "Monitor /ops_status and /healthz for ongoing health",
            },
        ],
    }


@app.route("/network_health_dashboard")
def network_health_dashboard():
    config = load_chain_config()
    security_config = config.get("security", {})
    chain = load_chain()
    peers_data = healthy_peers()
    mempool = load_mempool()
    trust_policy = config.get("peer_trust_policy", {})
    node_config = read_json("node_config.json", {})
    node_id = node_config.get("node_id", "unknown")
    return {
        "status": "ok",
        "timestamp": time.time(),
        "timestamp_human": format_human_time(time.time()),
        "node": {
            "node_id": node_id,
            "version": "kwd-node-1.2.0",
            "network_id": config.get("network_id"),
            "port": node_config.get("port", 5000),
        },
        "blockchain": {
            "height": len(chain),
            "latest_block_hash": chain[-1].get("hash") if chain else None,
            "latest_block_time": chain[-1].get("timestamp") if chain else None,
            "latest_block_time_human": format_human_time(chain[-1].get("timestamp") if chain else None),
            "difficulty": chain[-1].get("difficulty") if chain else 1,
        },
        "network": {
            "total_peers": len(load_peers()),
            "healthy_peers": len(peers_data),
            "seed_nodes": len(config.get("seed_nodes", [])),
            "blacklisted_peers": len(load_blacklist()),
        },
        "mempool": {
            "pending_transactions": len(mempool),
            "total_pending_fees": get_pending_fee_total(mempool),
        },
        "security": {
            "tls_enabled": bool(security_config.get("tls_enabled", False)),
            "rate_limiting_enabled": bool(security_config.get("rate_limit", 0) > 0),
            "public_api_enabled": bool(security_config.get("public_api_enabled", True)),
            "rollout_safety_mode": bool(security_config.get("rollout_safety_mode", False)),
            "trust_policy_enabled": bool(trust_policy),
        },
        "bootstrap_state": {
            "state": read_json("bootstrap_state.json", {}).get("state", "not_started"),
            "last_bootstrap_time": read_json("bootstrap_state.json", {}).get("timestamp"),
            "last_bootstrap_time_human": format_human_time(read_json("bootstrap_state.json", {}).get("timestamp")),
            "seed_nodes_count": len(config.get("seed_nodes", [])),
        },
        "peer_health": peers_data,
    }


@app.route("/network_info")
def network_info():
    config = load_chain_config()
    chain = load_chain()
    mempool = load_mempool()
    peers = load_peers()
    healthy = healthy_peers()
    node_config = read_json("node_config.json", {})
    node_id = node_config.get("node_id", "unknown")
    return {
        "timestamp": time.time(),
        "node": {
            "node_id": node_id,
            "version": "kwd-node-1.2.0",
            "network_id": config.get("network_id"),
            "port": node_config.get("port", 5000),
        },
        "blockchain": {
            "height": len(chain),
            "latest_block_hash": chain[-1].get("hash") if chain else None,
        },
        "network": {
            "total_peers": len(peers),
            "healthy_peers": len(healthy),
            "seed_nodes": config.get("seed_nodes", []),
        },
        "mempool": {
            "pending_transactions": len(mempool),
        },
    }


@app.route("/sync_peers")
def sync_peers():
    peers, added, errors = sync_peer_list()
    return {"message": "Peer list synced", "added": added, "errors": errors, "peers": peers}


@app.route("/peer_health")
def peer_health():
    return peer_health_data()


@app.route("/sync_mempool")
def sync_mempool():
    sync_peer_list()
    cleanup_blacklist()
    chain = load_chain()
    local_mempool = load_mempool()
    known_txids = {tx_id(tx) for tx in local_mempool}
    known_txids.update({tx_id(tx_data) for _block, tx_data, _tx in iter_transactions(chain)})
    added = 0
    errors = []
    healthy = healthy_peers()
    peers_to_query = [peer_info["peer"] for peer_info in healthy] if healthy else load_peers()
    for peer in peers_to_query:
        peer_url = normalize_peer(peer)
        if not peer_url:
            continue
        try:
            response = signed_get(f"{peer_url}/mempool", path="/mempool", timeout=5)
            response.raise_for_status()
            for tx_data in response.json():
                current_txid = tx_id(tx_data)
                if current_txid in known_txids:
                    continue
                valid, error = validate_transaction(tx_data, chain, local_mempool)
                if not valid:
                    errors.append({"peer": peer, "txid": current_txid, "error": error})
                    continue
                local_mempool.append(tx_data)
                known_txids.add(current_txid)
                added += 1
        except Exception as exc:
            record_peer_failure(peer_url, str(exc))
            errors.append({"peer": peer, "error": str(exc)})
    save_mempool(local_mempool, reason="sync_mempool")
    return {
        "message": "Mempool sync complete",
        "added": added,
        "pending": len(local_mempool),
        "peers_queried": len(peers_to_query),
        "errors": errors,
    }

@app.route("/blacklist")
def blacklist():
    cleanup_blacklist()
    return load_blacklist()


@app.route("/peer_failures")
def peer_failures():
    return load_peer_failures()


@app.route("/peer_reputation")
def peer_reputation():
    return peer_health_data()


def status_data():
    chain = load_chain()
    valid, error = validate_chain_data(chain)
    mempool_data = load_mempool()
    peers = load_peers()
    peer_health = peer_health_data()
    return {
        "node_info": node_info(),
        "chain": {
            "length": len(chain),
            "valid": valid,
            "error": error,
            "work": chain_work(chain),
        },
        "mempool": {
            "size": len(mempool_data),
            "pending_fees": get_pending_fee_total(mempool_data),
        },
        "orphans": {"count": len(load_orphans())},
        "peers": {
            "total": len(peers),
            "healthy": sum(1 for item in peer_health if item.get("online")),
        },
        "peer_health": peer_health,
        "blacklist": load_blacklist(),
        "peer_failures": load_peer_failures(),
    }


@app.route("/status")
def status():
    return status_data()


@app.route("/unblacklist_peer", methods=["POST"])
def unblacklist_peer_route():
    data = request.get_json(silent=True) or {}
    peer = data.get("peer")
    if not peer:
        return {"error": "Missing peer"}, 400
    if unblacklist_peer(peer):
        return {"message": "Peer removed from blacklist", "peer": peer}
    return {"error": "Peer not found or already unblacklisted"}, 404


@app.route("/generate_wallet")
def generate_wallet():
    wallet = create_wallet()
    register_wallet(address=wallet["address"], public_key=wallet["public_key"], wallet=wallet["address"], metadata={"source": "local"})
    return wallet


@app.route("/import_wallet", methods=["POST"])
def import_wallet():
    data = request.get_json(silent=True) or {}
    private_key = data.get("private_key")
    if not private_key:
        return {"error": "Missing private_key"}, 400
    try:
        _, wallet = wallet_from_private_key(private_key)
    except Exception as exc:
        return {"error": f"Invalid private key: {exc}"}, 400

    register_public_key(wallet["address"], wallet["public_key"])
    register_wallet(address=wallet["address"], public_key=wallet["public_key"], wallet=wallet["address"], metadata={"source": "local"})
    return wallet


@app.route("/backup_wallet", methods=["POST"])
def backup_wallet():
    data = request.get_json(silent=True) or {}
    address = data.get("address")
    if not address:
        return {"error": "Missing address"}, 400

    private_key = load_wallet_secret(address)
    if not private_key:
        return {"error": "Wallet not found"}, 404

    wallet_record = {
        "address": address,
        "private_key": private_key,
        "public_key": None,
    }
    public_record = read_json(PUBLIC_KEYS_FILE, [])
    for item in public_record:
        if item.get("address") == address:
            wallet_record["public_key"] = item.get("public_key")
            break
    return wallet_record


@app.route("/stats")
@app.route("/dashboard")
@app.route("/network_stats")
def dashboard():
    chain = load_chain()
    peers = load_peers()
    wallets = set()
    tx_count = 0
    for _block, _tx_data, tx in iter_transactions(chain):
        tx_count += 1
        wallets.add(tx.get("from"))
        wallets.add(tx.get("to"))
    latest = chain[-1] if chain else {}
    return {
        "blocks": len(chain),
        "transactions": tx_count,
        "wallets": len([wallet for wallet in wallets if wallet]),
        "peers": len(peers),
        "supply": get_total_supply(chain),
        "difficulty": latest.get("difficulty", 0),
        "next_difficulty": calculate_next_difficulty(chain),
        "chain_work": chain_work(chain),
        "mempool": len(load_mempool()),
        "orphans": len(load_orphans()),
        "peer_health": peer_health_data(),
    }


@app.route("/supply")
def supply():
    return {"total_supply": get_total_supply(load_chain())}


@app.route("/circulating_supply")
@app.route("/circulating-supply")
def circulating_supply():
    chain = load_chain()
    total_supply = get_total_supply(chain)
    config = load_chain_config()
    max_supply = float(config.get("max_supply", 21000000))
    remaining = max(0.0, max_supply - total_supply)
    return {
        "total_supply": total_supply,
        "circulating_supply": total_supply,
        "remaining_supply": remaining,
        "max_supply": max_supply,
    }


@app.route("/richlist")
def richlist():
    chain = load_chain()
    wallets = set()
    counts = {}
    for _block, _tx_data, tx in iter_transactions(chain):
        wallets.add(tx.get("from"))
        wallets.add(tx.get("to"))
        counts[tx.get("from")] = counts.get(tx.get("from"), 0) + 1
        counts[tx.get("to")] = counts.get(tx.get("to"), 0) + 1
    data = [
        {
            "wallet": wallet,
            "balance": get_balance(wallet, chain),
            "tx_count": counts.get(wallet, 0),
        }
        for wallet in wallets
        if wallet and wallet != "NETWORK"
    ]
    data.sort(key=lambda item: item["balance"], reverse=True)
    return data


@app.route("/wallets")
def wallets():
    wallets_seen = set()
    for _block, _tx_data, tx in iter_transactions(load_chain()):
        wallets_seen.add(tx.get("from"))
        wallets_seen.add(tx.get("to"))
    return sorted(wallet for wallet in wallets_seen if wallet)


@app.route("/wallet/<address>")
def wallet_info(address):
    return wallet_summary(address, load_chain())


@app.route("/wallet/<address>/pending")
def wallet_pending(address):
    result = []
    for tx_data in load_mempool():
        tx = tx_payload(tx_data)
        if tx.get("from") == address or tx.get("to") == address:
            item = dict(tx)
            item["txid"] = tx.get("txid") or tx_id(tx_data)
            result.append(item)
    return result


@app.route("/wallet/<address>/nonce")
def wallet_nonce(address):
    chain = load_chain()
    mempool = load_mempool()
    return {"address": address, "next_nonce": get_next_nonce(address, chain, mempool)}


@app.route("/wallet/<address>/stats")
def wallet_stats(address):
    chain = load_chain()
    received = 0.0
    sent = 0.0
    balance = 0.0
    tx_count = 0
    first_tx = None
    last_tx = None

    for block, tx_data, tx in iter_transactions(chain):
        txid = tx.get("txid") or tx_id(tx_data)
        if tx.get("to") == address:
            amount = float(tx.get("amount", 0))
            received += amount
            balance += amount
            tx_count += 1
            current = {
                "txid": txid,
                "block": block["index"],
                "timestamp": tx.get("timestamp"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "amount": amount,
                "fee": tx.get("fee", 0),
            }
            if first_tx is None:
                first_tx = current
            last_tx = current
        if tx.get("from") == address:
            amount = float(tx.get("amount", 0))
            fee = float(tx.get("fee", 0))
            spent = amount + fee
            sent += spent
            balance -= spent
            tx_count += 1
            current = {
                "txid": txid,
                "block": block["index"],
                "timestamp": tx.get("timestamp"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "amount": amount,
                "fee": fee,
            }
            if first_tx is None:
                first_tx = current
            last_tx = current

    return {
        "address": address,
        "total_received": received,
        "total_sent": sent,
        "current_balance": balance,
        "transaction_count": tx_count,
        "first_transaction": first_tx,
        "last_transaction": last_tx,
    }


@app.route("/wallet/<address>/balance_history")
def wallet_balance_history(address):
    chain = load_chain()
    balance = 0.0
    history = []
    for block in chain:
        for tx_data in block.get("transactions", []):
            tx = tx_payload(tx_data)
            if not isinstance(tx, dict):
                continue
            if tx.get("to") == address:
                balance += float(tx.get("amount", 0))
            if tx.get("from") == address:
                balance -= float(tx.get("amount", 0)) + float(tx.get("fee", tx.get("fees", 0)))
        history.append({
            "block": block.get("index"),
            "timestamp": block.get("timestamp"),
            "balance": balance,
        })
    return {"address": address, "history": history}


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _collect_chain_metrics(chain=None):
    chain = chain or load_chain()
    tx_count = 0
    reward_total = 0.0
    reward_points = []
    supply_points = []
    difficulty_points = []
    fee_values = []
    wallet_records = []

    for index, block in enumerate(chain, start=1):
        block_reward = 0.0
        for tx_data in block.get("transactions", []):
            tx = tx_payload(tx_data)
            if not isinstance(tx, dict):
                continue
            tx_count += 1
            if tx.get("from") == "NETWORK":
                block_reward += _safe_float(tx.get("amount") or tx.get("base_reward") or 0)
            fee = tx.get("fee") if tx.get("fee") is not None else tx.get("fees")
            if fee is not None:
                fee_values.append(_safe_float(fee))
            if tx.get("from"):
                wallet_records.append(tx.get("from"))
            if tx.get("to"):
                wallet_records.append(tx.get("to"))
        reward_total += block_reward
        reward_points.append({
            "index": block.get("index", index),
            "height": block.get("index", index),
            "reward": block_reward,
            "timestamp": block.get("timestamp"),
        })
        supply_points.append({
            "index": block.get("index", index),
            "height": block.get("index", index),
            "supply": get_total_supply(chain[:index]),
        })
        difficulty_points.append({
            "index": block.get("index", index),
            "difficulty": block.get("difficulty", 0),
            "timestamp": block.get("timestamp"),
        })

    wallets = read_json(WALLETS_FILE, [])
    if isinstance(wallets, list):
        wallet_records.extend(item.get("address") or item.get("wallet") for item in wallets if isinstance(item, dict))
    wallet_records = [wallet for wallet in wallet_records if wallet]
    return {
        "chain": chain,
        "tx_count": tx_count,
        "reward_total": reward_total,
        "reward_points": reward_points,
        "supply_points": supply_points,
        "difficulty_points": difficulty_points,
        "fee_values": fee_values,
        "wallet_records": list(dict.fromkeys(wallet_records)),
    }


@app.route("/latest_wallets")
def latest_wallets():
    wallets = read_json(WALLETS_FILE, [])
    if not isinstance(wallets, list):
        wallets = []
    results = []
    for item in wallets:
        if isinstance(item, dict):
            address = item.get("address") or item.get("wallet")
            if address:
                results.append({"address": address, "public_key": item.get("public_key")})
    return results[-10:][::-1]


@app.route("/network_supply_history")
def network_supply_history():
    metrics = _collect_chain_metrics()
    return metrics["supply_points"]


@app.route("/block_reward_history")
def block_reward_history():
    metrics = _collect_chain_metrics()
    return metrics["reward_points"]


@app.route("/address/<wallet>/tokens")
def address_tokens(wallet):
    chain = load_chain()
    balance = get_balance(wallet, chain)
    return {
        "address": wallet,
        "tokens": [
            {
                "symbol": "BASE",
                "name": "Native Coin",
                "balance": balance,
                "type": "native",
            }
        ],
    }


@app.route("/network_hashrate")
def network_hashrate():
    chain = load_chain()
    if len(chain) < 2:
        return {"estimated_hashrate": 0.0, "unit": "hashes/sec", "blocks": len(chain)}
    start_time = float(chain[0].get("timestamp", 0))
    end_time = float(chain[-1].get("timestamp", start_time))
    elapsed = max(1.0, end_time - start_time)
    work = chain_work(chain)
    return {"estimated_hashrate": work / elapsed, "unit": "hashes/sec", "blocks": len(chain)}


@app.route("/difficulty_history")
def difficulty_history():
    metrics = _collect_chain_metrics()
    return metrics["difficulty_points"]


@app.route("/fee_statistics")
def fee_statistics():
    metrics = _collect_chain_metrics()
    values = metrics["fee_values"]
    if not values:
        return {"count": 0, "average_fee": 0.0, "min_fee": 0.0, "max_fee": 0.0}
    return {
        "count": len(values),
        "average_fee": sum(values) / len(values),
        "min_fee": min(values),
        "max_fee": max(values),
    }


@app.route("/network_overview")
def network_overview():
    chain = load_chain()
    metrics = _collect_chain_metrics(chain)
    latest = chain[-1] if chain else {}
    return {
        "status": "ok",
        "blocks": len(chain),
        "transactions": metrics["tx_count"],
        "supply": get_total_supply(chain),
        "difficulty": latest.get("difficulty", 0),
        "next_difficulty": calculate_next_difficulty(chain),
        "mempool": len(load_mempool()),
        "peers": len(load_peers()),
        "wallets": len(metrics["wallet_records"]),
        "hashrate": network_hashrate().get("estimated_hashrate"),
        "fees": fee_statistics(),
        "latest_block": latest,
    }


@app.route("/wallet_count")
def wallet_count():
    return {"wallet_count": len(read_json(WALLETS_FILE, []))}


@app.route("/peer_list")
def peer_list():
    return load_peers()


@app.route("/supply_history")
def supply_history():
    return network_supply_history()


@app.route("/block_time_stats")
def block_time_stats():
    chain = load_chain()
    if len(chain) < 2:
        return {"count": 0, "average_block_time": 0.0, "min_block_time": 0.0, "max_block_time": 0.0}
    times = []
    for prior, current in zip(chain, chain[1:]):
        try:
            times.append(abs(float(current.get("timestamp", 0)) - float(prior.get("timestamp", 0))))
        except (TypeError, ValueError, OverflowError):
            continue
    if not times:
        return {"count": 0, "average_block_time": 0.0, "min_block_time": 0.0, "max_block_time": 0.0}
    return {
        "count": len(times),
        "average_block_time": sum(times) / len(times),
        "min_block_time": min(times),
        "max_block_time": max(times),
    }


@app.route("/network_summary")
def network_summary():
    overview = network_overview()
    return {
        **overview,
        "difficulty_history": difficulty_history(),
        "supply_history": supply_history(),
        "block_time_stats": block_time_stats(),
        "wallet_count": wallet_count()["wallet_count"],
        "peer_list": peer_list(),
        "api_version": api_version(),
    }


@app.route("/miner_stats")
@app.route("/validator_stats")
def miner_stats():
    metrics = _collect_chain_metrics()
    return {
        "blocks_mined": len(metrics["reward_points"]),
        "total_rewards": metrics["reward_total"],
        "latest_reward": metrics["reward_points"][-1]["reward"] if metrics["reward_points"] else 0.0,
        "average_reward": (
            sum(item["reward"] for item in metrics["reward_points"]) / len(metrics["reward_points"])
            if metrics["reward_points"] else 0.0
        ),
    }


@app.route("/api_version")
def api_version():
    return {
        "version": "1.0.0",
        "api_version": "v1",
        "name": "2026 Blockchain Node",
        "node_id": read_json("node_config.json", {}).get("node_id", "unknown"),
    }


@app.route("/version")
def version():
    config = load_chain_config()
    node_conf = read_json("node_config.json", {})
    return {
        "version": "1.0.0",
        "node_version": "kwd-node-1.2.0",
        "api_version": "v1",
        "node_id": node_conf.get("node_id", "unknown"),
        "network_id": config.get("network_id"),
        "uptime_seconds": int(time.time() - START_TIME),
    }


def node_health_summary():
    config = load_chain_config()
    security_config = config.get("security", {})
    peer_health = peer_health_data()
    healthy_count = sum(1 for item in peer_health if item.get("online"))
    chain = load_chain()
    return {
        "status": "ok" if healthy_count >= 0 else "degraded",
        "uptime_seconds": int(time.time() - START_TIME),
        "uptime_human": format_human_duration(int(time.time() - START_TIME)),
        "blocks": len(chain),
        "mempool": len(load_mempool()),
        "peers": len(load_peers()),
        "healthy_peers": healthy_count,
        "monitoring_enabled": bool(security_config.get("monitoring_enabled", True)),
        "storage": {
            "sqlite": os.path.exists("blockchain_state.sqlite3"),
            "wallet_secrets": os.path.exists(WALLET_SECRETS_FILE),
        },
        "node": {
            "port": read_json("node_config.json", {}).get("port"),
            "network_id": config.get("network_id"),
        },
        "security": {
            "encrypt_private_keys": security_config.get("encrypt_private_keys", True),
            "rate_limit": security_config.get("rate_limit", 120),
            "rate_limit_window_seconds": security_config.get("rate_limit_window_seconds", 60),
            "rate_limit_ban_seconds": security_config.get("rate_limit_ban_seconds", 60),
            "tls_enabled": security_config.get("tls_enabled", False),
            "monitoring_enabled": security_config.get("monitoring_enabled", True),
            "peer_shared_secret_configured": bool(security_config.get("peer_shared_secret")),
        },
        "network": {
            "peer_count": len(load_peers()),
            "healthy_peers": healthy_count,
            "peer_health": peer_health,
        },
        "events": load_node_events()[-10:],
        "bootstrap_state": config.get("bootstrap_state", {}),
    }


@app.route("/ops_status")
def ops_status():
    return node_health_summary()


@app.route("/audit_log")
def audit_log():
    if not is_admin_authorized():
        return jsonify({"error": "Admin authentication required"}), 403
    return jsonify(load_audit_log())


@app.route("/approval_history")
def approval_history():
    if not is_admin_authorized():
        return jsonify({"error": "Admin authentication required"}), 403
    return jsonify(load_approval_history())


@app.route("/healthz")
def healthz():
    summary = node_health_summary()
    return {
        "status": summary["status"],
        "uptime_seconds": summary["uptime_seconds"],
        "blocks": summary["blocks"],
        "mempool": summary["mempool"],
        "peers": summary["peers"],
        "healthy_peers": summary["healthy_peers"],
        "monitoring_enabled": summary["monitoring_enabled"],
        "last_events": summary["events"][-5:],
        "node_health": summary,
    }


@app.route("/health")
def health():
    """Simple health check used by load balancers and monitoring."""
    summary = node_health_summary()
    status_code = 200 if summary.get("status") == "ok" else 503
    payload = {
        "status": summary["status"],
        "uptime_seconds": summary["uptime_seconds"],
        "blocks": summary["blocks"],
        "mempool": summary["mempool"],
        "peers": summary["peers"],
    }
    return payload, status_code


@app.route("/genesis")
def genesis():
    """Return the genesis block for this node's chain configuration."""
    chain = load_chain()
    if chain:
        genesis_block = chain[0]
    else:
        genesis_block = load_chain_config().get("genesis_block") or None
    if genesis_block is None:
        return {"error": "Genesis block not found"}, 404
    return genesis_block


@app.route("/mining_info")
def mining_info():
    chain = load_chain()
    config = load_chain_config()
    latest_block = chain[-1] if chain else None
    current_height = len(chain)
    current_difficulty = int(latest_block.get("difficulty", 1)) if latest_block else int(config.get("min_difficulty", 1))
    next_difficulty = calculate_next_difficulty(chain)
    current_reward = calculate_reward(current_height, get_total_supply(chain))
    return {
        "height": current_height,
        "current_difficulty": current_difficulty,
        "next_difficulty": next_difficulty,
        "current_reward": current_reward,
        "target_block_time": config.get("target_block_time", TARGET_BLOCK_TIME),
        "difficulty_adjustment_interval": config.get(
            "difficulty_adjustment_interval",
            DIFFICULTY_ADJUSTMENT_INTERVAL,
        ),
        "network_id": config.get("network_id"),
    }


@app.route("/reward_schedule")
def reward_schedule():
    config = load_chain_config()
    return {
        "initial_reward": config.get("initial_reward"),
        "reward_schedule": config.get("reward_schedule", []),
        "network_id": config.get("network_id"),
    }


@app.route("/halving_info")
def halving_info():
    chain = load_chain()
    config = load_chain_config()
    height = len(chain)
    supply = get_total_supply(chain)
    max_supply = float(config.get("max_supply", 21000000))
    current_reward = calculate_reward(height, supply)
    next_halving_height = None
    next_reward = current_reward
    for item in config.get("reward_schedule", []):
        if height < int(item["height"]):
            next_halving_height = int(item["height"])
            next_reward = float(item["reward"])
            break
    return {
        "current_height": height,
        "current_reward": current_reward,
        "next_halving_height": next_halving_height,
        "blocks_until_halving": (next_halving_height - height) if next_halving_height else 0,
        "next_reward": next_reward,
        "total_supply_mined": supply,
        "max_supply": max_supply,
        "percent_mined": round((supply / max_supply) * 100, 6) if max_supply else 0,
    }


@app.route("/merkle_proof/<txid>")
def merkle_proof(txid):
    from core import compute_merkle_root
    chain = load_chain()
    for block in chain:
        txs = block.get("transactions", [])
        txids = [tx_id(t) or ("0" * 64) for t in txs]
        if txid in txids:
            idx = txids.index(txid)
            level = list(txids)
            proof = []
            while len(level) > 1:
                if len(level) % 2 == 1:
                    level.append(level[-1])
                sibling_idx = idx ^ 1
                position = "right" if idx % 2 == 0 else "left"
                proof.append({"position": position, "hash": level[sibling_idx]})
                next_level = []
                for i in range(0, len(level), 2):
                    combined = f"{level[i]}{level[i + 1]}".encode("utf-8")
                    next_level.append(hashlib.sha256(hashlib.sha256(combined).digest()).hexdigest())
                level = next_level
                idx //= 2
            computed_root = level[0] if level else ("0" * 64)
            stored_root = block.get("merkle_root") or compute_merkle_root(txs)
            return {
                "txid": txid,
                "block_index": block.get("index"),
                "block_hash": block.get("hash"),
                "merkle_root": stored_root,
                "proof_steps": proof,
                "spv_verified": computed_root == stored_root,
            }
    return {"error": "Transaction not found in any mined block"}, 404


@app.route("/faucet/<address>", methods=["GET", "POST"])
def faucet(address):
    wallet1 = read_json("wallet1.json", {})
    if not wallet1.get("private_key"):
        return {"error": "Faucet wallet1.json not configured"}, 400
    if wallet1.get("address") == address:
        return {"error": "Cannot send faucet coins to the faucet wallet itself"}, 400
    chain = load_chain()
    mempool_data = load_mempool()
    try:
        signed_tx = create_signed_transaction(
            wallet1["private_key"],
            address,
            10.0,
            fee=1.0,
            chain=chain,
            mempool=mempool_data,
        )
    except Exception as exc:
        return {"error": str(exc)}, 400
    valid, error = validate_transaction(signed_tx, chain, mempool_data)
    if not valid:
        return {"error": error}, 400
    mempool_data.append(signed_tx)
    save_mempool(mempool_data, reason="faucet payout")
    broadcast_transaction(signed_tx)
    return {
        "message": "Faucet sent 10 KWD to your wallet!",
        "recipient": address,
        "amount": 10.0,
        "txid": tx_id(signed_tx),
    }


@app.route("/difficulty")
def difficulty():
    chain = load_chain()
    config = load_chain_config()
    latest_block = chain[-1] if chain else None
    current_difficulty = int(latest_block.get("difficulty", 1)) if latest_block else int(config.get("min_difficulty", 1))
    return {
        "height": len(chain),
        "current_difficulty": current_difficulty,
        "next_difficulty": calculate_next_difficulty(chain),
        "target_block_time": config.get("target_block_time", TARGET_BLOCK_TIME),
        "difficulty_adjustment_interval": config.get(
            "difficulty_adjustment_interval",
            DIFFICULTY_ADJUSTMENT_INTERVAL,
        ),
        "network_id": config.get("network_id"),
    }


@app.route("/metrics")
def metrics():
    summary = node_health_summary()
    return {
        "blocks": summary["blocks"],
        "mempool": summary["mempool"],
        "peers": summary["peers"],
        "healthy_peers": summary["healthy_peers"],
        "orphans": len(load_orphans()),
        "events": summary["events"],
        "uptime_seconds": summary["uptime_seconds"],
        "peer_health": summary["network"]["peer_health"],
        "node_health": summary,
    }


@app.route("/recover_state", methods=["POST"])
def recover_state():
    data = request.get_json(silent=True) or {}
    target = data.get("path") or CHAIN_FILE
    default = data.get("default")
    recovered = recover_state_file(target, default=default)
    return {
        "message": "State recovery attempted",
        "path": target,
        "recovered": recovered is not None,
        "value": recovered,
    }


@app.route("/transaction/<txid>")
@app.route("/tx/<txid>")
def transaction(txid):
    chain = load_chain()
    current_height = len(chain)
    for block, tx_data, tx in iter_transactions(chain):
        current_txid = tx.get("txid") or tx_id(tx_data)
        if current_txid == txid:
            confirmations = max(0, current_height - block["index"] + 1)
            return {
                "txid": current_txid,
                "block": block["index"],
                "confirmations": confirmations,
                "transaction": tx,
                "timestamp": tx.get("timestamp"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "amount": tx.get("amount"),
                "fee": tx.get("fee"),
                "signature": tx_signature(tx_data),
            }
    mempool = load_mempool() or []
    for tx_data in mempool:
        current_txid = tx_id(tx_data)
        if current_txid == txid:
            tx = tx_payload(tx_data)
            return {
                "txid": current_txid,
                "block": None,
                "confirmations": 0,
                "transaction": tx,
                "timestamp": tx.get("timestamp"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "amount": tx.get("amount"),
                "fee": tx.get("fee"),
                "signature": tx_signature(tx_data),
            }
    return {"error": "Transaction not found"}, 404


@app.route("/peers")
def peers():
    peer_list = read_json(PEERS_FILE, [])
    if isinstance(peer_list, str):
        peer_list = [peer_list]
    self_url = get_self_peer_url()
    for seed in (load_chain_config().get("seed_nodes", []) or []):
        normalized = normalize_peer(seed)
        if normalized and normalized.rstrip("/") != self_url.rstrip("/"):
            stored = normalized.replace("http://", "").replace("https://", "")
            if stored not in peer_list:
                peer_list.append(stored)
    return peer_list


@app.route("/register_peer", methods=["POST"])
def register_peer():
    data = request.get_json(silent=True) or {}
    if not is_peer_registration_authorized(data):
        return {"error": "Peer registration authorization failed"}, 403
    peer = data.get("peer")
    normalized = normalize_peer(peer)
    if not normalized:
        return {"error": "Missing peer"}, 400
    if is_self_peer(normalized):
        return {"message": "Peer is self, ignored"}, 200
    if not is_peer_trusted(normalized):
        return {"error": "Peer trust policy rejected this peer"}, 403
    if is_peer_blacklisted(normalized):
        return {"error": "Peer is blacklisted"}, 400
    peer_info = peer_node_info(normalized)
    if not peer_info:
        return {"error": "Peer validation failed or incompatible", "peer": peer}, 400
    stored_peer = normalized.replace("http://", "").replace("https://", "")
    peers_data = load_peers()
    if stored_peer not in peers_data:
        peers_data.append(stored_peer)
        write_json(PEERS_FILE, peers_data)
        message = "Peer added"
    else:
        message = "Peer already known"
    discovered_peers, discovered_added, errors = sync_peer_list()
    return {
        "message": message,
        "peers": peers_data,
        "discovered_peers": discovered_peers,
        "discovered_added": discovered_added,
        "errors": errors,
    }


@app.route("/blockstats")
def blockstats():
    chain = load_chain()
    latest = chain[-1] if chain else {}
    return {
        "latest_block": latest.get("index", 0),
        "difficulty": latest.get("difficulty", 0),
        "total_blocks": len(chain),
        "hash": latest.get("hash"),
    }


def perform_search(query):
    chain = load_chain()
    if query.isdigit():
        index = int(query)
        for block in chain:
            if block.get("index") == index:
                return {"type": "block", "data": block}
    for block in chain:
        if block.get("hash") == query:
            return {"type": "block", "data": block}
    for block, tx_data, tx in iter_transactions(chain):
        current_txid = tx.get("txid") or tx_id(tx_data)
        if current_txid == query:
            return {"type": "transaction", "txid": current_txid, "block": block["index"]}
        if tx.get("from") == query or tx.get("to") == query:
            return {"type": "wallet", "address": query}
    return {"error": "Not found"}, 404


@app.route("/search")
def search_query():
    query = request.args.get("q", "") or ""
    query = str(query).strip()
    if not query:
        return {"error": "Missing query parameter q"}, 400
    return perform_search(query)


@app.route("/search/<query>")
def search(query):
    return perform_search(query)


@app.route("/latest_blocks")
def latest_blocks():
    return load_chain()[-10:]


@app.route("/charts")
def charts():
    chain = load_chain()
    supply_points = []
    block_points = []
    difficulty_points = []
    for block in chain:
        index = block.get("index")
        timestamp = block.get("timestamp")
        supply_points.append({"x": index, "y": get_total_supply(chain[:index])})
        block_points.append({"x": index, "y": index})
        difficulty_points.append({"x": index, "y": block.get("difficulty", 0)})
    return {
        "supply": supply_points,
        "blocks": block_points,
        "difficulty": difficulty_points,
    }


@app.route("/export/chain")
def export_chain():
    chain = load_chain()
    return {
        "chain": chain,
        "height": len(chain),
        "exported_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


@app.route("/latest_transactions")
def latest_transactions():
    txs = []
    for block in reversed(load_chain()):
        for tx_data in block.get("transactions", []):
            tx = tx_payload(tx_data)
            item = dict(tx)
            item["block"] = block["index"]
            item["txid"] = tx.get("txid") or tx_id(tx_data)
            txs.append(item)
            if len(txs) >= 25:
                return txs
    return txs


@app.route("/network_activity")
def network_activity():
    chain = load_chain()
    recent_blocks = chain[-10:][::-1]
    recent_transactions = []
    for block in reversed(chain):
        for tx_data in block.get("transactions", []):
            tx = tx_payload(tx_data)
            item = dict(tx)
            item["block"] = block.get("index")
            item["txid"] = tx.get("txid") or tx_id(tx_data)
            recent_transactions.append(item)
            if len(recent_transactions) >= 25:
                break
        if len(recent_transactions) >= 25:
            break
    return {
        "height": len(chain),
        "latest_blocks": recent_blocks,
        "latest_transactions": recent_transactions,
    }


@app.route("/api_docs")
def api_docs():
    html = """
    <!doctype html>
    <html>
    <head>
        <meta charset=\"utf-8\">
        <title>Blockchain API Documentation</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 2rem; }
            code { background: #f3f3f3; padding: 0.1rem 0.3rem; }
            li { margin-bottom: 0.4rem; }
        </style>
    </head>
    <body>
        <h1>Blockchain API Documentation</h1>
        <p>This node exposes the following JSON endpoints:</p>
        <ul>
            <li><code>GET /health</code></li>
            <li><code>GET /version</code></li>
            <li><code>GET /network_info</code></li>
            <li><code>GET /block/&lt;index&gt;</code></li>
            <li><code>GET /wallet/&lt;address&gt;/balance</code></li>
            <li><code>GET /wallet/&lt;address&gt;/transactions</code></li>
            <li><code>GET /transactions</code></li>
            <li><code>GET /pending</code></li>
            <li><code>GET /charts</code></li>
            <li><code>GET /export/chain</code></li>
            <li><code>GET /export/block/&lt;height&gt;</code></li>
        </ul>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


@app.route("/explorer")
def explorer():
    with open("explorer.html", "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/send")
def send_page():
    with open("send.html", "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/blockview")
def blockview_page():
    with open("block.html", "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


def generate_self_signed_tls_material(cert_path, key_path):
    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(x509.NameOID.COMMON_NAME, u"localhost"),
    ])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    with open(cert_path, "wb") as handle:
        handle.write(certificate.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as handle:
        handle.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    return cert_path, key_path


def get_tls_context():
    security_config = load_chain_config().get("security", {})
    if not security_config.get("tls_enabled", False):
        return None
    cert_path = security_config.get("tls_cert_path") or "cert.pem"
    key_path = security_config.get("tls_key_path") or "key.pem"
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        generate_self_signed_tls_material(cert_path, key_path)
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return (cert_path, key_path)
    return None


def _wait_for_flask_ready(port, timeout_seconds=15):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _run_server(port, tls_context):
    if tls_context:
        app.run(host="0.0.0.0", port=port, ssl_context=tls_context)
    else:
        app.run(host="0.0.0.0", port=port)


def _run_startup_sync(max_attempts=5, delay_seconds=2.0):
    print("[Startup] Waiting before bootstrap...")
    time.sleep(3)
    print("[Startup] Bootstrapping...")
    try:
        bootstrap_on_startup()
    except Exception as exc:
        print(f"Automatic bootstrap failed: {exc}")

    last_chain_error = None
    for attempt in range(1, max_attempts + 1):
        print(f"[Startup] Synchronizing chain (attempt {attempt}/{max_attempts})...")
        try:
            sync_chain()
            last_chain_error = None
            break
        except Exception as exc:
            last_chain_error = exc
            print(f"Startup chain sync failed on attempt {attempt}: {exc}")
            if attempt < max_attempts:
                time.sleep(delay_seconds)

    if last_chain_error is not None:
        print(f"Startup chain sync exhausted retries: {last_chain_error}")

    last_mempool_error = None
    for attempt in range(1, max_attempts + 1):
        print(f"[Startup] Synchronizing mempool (attempt {attempt}/{max_attempts})...")
        try:
            sync_mempool()
            last_mempool_error = None
            break
        except Exception as exc:
            last_mempool_error = exc
            print(f"Startup mempool sync failed on attempt {attempt}: {exc}")
            if attempt < max_attempts:
                time.sleep(delay_seconds)

    if last_mempool_error is not None:
        print(f"Startup mempool sync exhausted retries: {last_mempool_error}")

    print("[Startup] Startup synchronization complete.")


def _start_runtime_services(port, tls_context):
    server_thread = threading.Thread(target=_run_server, args=(port, tls_context), daemon=True)
    server_thread.start()

    if _wait_for_flask_ready(port):
        print("[Startup] Flask ready")
        startup_thread = threading.Thread(target=_run_startup_sync, daemon=True)
        startup_thread.start()
    else:
        print("[Startup] Flask did not become ready")

    return server_thread


if __name__ == "__main__":
    config = read_json("node_config.json", {})
    port = int(os.environ.get("KWD_PORT", config.get("port", 5000)))
    tls_context = get_tls_context()

    server_thread = _start_runtime_services(port, tls_context)
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=1)
    except KeyboardInterrupt:
        print("[Startup] Shutting down")

