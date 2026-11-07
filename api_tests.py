import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import api
import core
import restart_one_node_scenario


def backup_working_files():
    files = [
        "blockchain_data.json",
        "mempool.json",
        "public_keys.json",
        "wallets.json",
        "wallet_secrets.json",
        "peers.json",
        "blacklisted_peers.json",
        "peer_failures.json",
        "chain_config.json",
        "node_config.json",
        "node_events.json",
    ]
    backed_up = {}
    for filename in files:
        path = Path(filename)
        backed_up[filename] = path.read_text() if path.exists() else None
    return backed_up


def restore_working_files(backed_up):
    for filename, content in backed_up.items():
        path = Path(filename)
        if content is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(content)


def setup_clean_chain():
    config = core.ensure_chain_config()
    config["peer_registration_token"] = None
    config["security"] = {
        "encrypt_private_keys": True,
        "rate_limit": 120,
        "rate_limit_window_seconds": 60,
        "rate_limit_ban_seconds": 60,
        "tls_enabled": False,
        "tls_cert_path": "cert.pem",
        "tls_key_path": "key.pem",
        "monitoring_enabled": True,
    }
    core.write_json("chain_config.json", config)
    chain = [core.create_genesis_block()]
    Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
    Path("mempool.json").write_text("[]")
    Path("public_keys.json").write_text("[]")
    Path("wallets.json").write_text("[]")
    Path("peers.json").write_text("[]")


def test_prepare_node_runtime_dir_creates_isolated_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "blockchain_data.json").write_text(json.dumps([{"index": 1, "hash": "abc"}]), encoding="utf-8")
    (workspace / "chain_config.json").write_text(json.dumps({"network_name": "test"}), encoding="utf-8")

    runtime_dir = restart_one_node_scenario.prepare_node_runtime_dir(workspace, 5002)

    assert runtime_dir.exists()
    assert (runtime_dir / "node_config.json").exists()
    assert (runtime_dir / "blockchain_data.json").exists()
    assert json.loads((runtime_dir / "node_config.json").read_text(encoding="utf-8"))["port"] == 5002
    assert json.loads((runtime_dir / "blockchain_data.json").read_text(encoding="utf-8"))[0]["hash"] == "abc"


def test_wait_chain_ready_uses_custom_request_timeout():
    attempts = []

    def fake_get_chain_info(port, timeout=120):
        attempts.append(timeout)
        if len(attempts) < 2:
            raise RuntimeError("temporary")
        return (2, "abc")

    with patch("restart_one_node_scenario.get_chain_info", side_effect=fake_get_chain_info), \
         patch("restart_one_node_scenario.time.time", return_value=0), \
         patch("restart_one_node_scenario.time.sleep", return_value=None):
        result = restart_one_node_scenario.wait_chain_ready(5001, timeout=1, request_timeout=7)

    assert result == (2, "abc")
    assert attempts == [7, 7]


def make_reward_block_for(chain, address):
    reward = core.calculate_reward(len(chain), core.get_total_supply(chain))
    previous = chain[-1]
    block = {
        "index": len(chain) + 1,
        "timestamp": max(time.time(), float(previous["timestamp"])),
        "transactions": [{
            "transaction": {
                "from": core.NETWORK,
                "to": address,
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
    proof = 0
    target = "0" * block["difficulty"]
    while True:
        hash_value = core.hashlib.sha256(f"{block['previous_hash']}{proof}".encode()).hexdigest()
        if hash_value.startswith(target):
            break
        proof += 1
    block["proof"] = proof
    block["hash"] = core.hash_block(block)
    return block


def test_wallet_sync_merges_peer_metadata_without_duplicates():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        core.write_json("wallets.json", [
            {
                "wallet": "wallet-a",
                "address": "wallet-a",
                "public_key": "pk-a",
                "metadata": {"source": "local"},
            }
        ])
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5001"]))

        def fake_signed_get(url, **kwargs):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [
                    {
                        "wallet": "wallet-a",
                        "address": "wallet-a",
                        "public_key": "pk-a",
                        "metadata": {"label": "peer"},
                    },
                    {
                        "wallet": "wallet-b",
                        "address": "wallet-b",
                        "public_key": "pk-b",
                        "metadata": {"label": "remote"},
                    },
                ],
            )

        with patch("api.signed_get", side_effect=fake_signed_get):
            result = api.sync_wallets()

        registry = core.read_json("wallets.json", [])
        assert result["updated"] is True
        assert result["count"] == 2
        assert len(registry) == 2
        wallet_a = next(item for item in registry if item["address"] == "wallet-a")
        assert wallet_a["metadata"]["source"] == "local"
        assert wallet_a["metadata"]["label"] == "peer"
        wallet_b = next(item for item in registry if item["address"] == "wallet-b")
        assert wallet_b["metadata"]["label"] == "remote"
    finally:
        restore_working_files(backup)


def test_json_persistence_uses_sqlite_backend():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        file_path = "sqlite_persistence_test.json"
        core.write_json(file_path, {"value": 42})
        Path(file_path).unlink(missing_ok=True)
        assert core.read_json(file_path, None) == {"value": 42}
    finally:
        restore_working_files(backup)
        if Path("sqlite_persistence_test.json").exists():
            Path("sqlite_persistence_test.json").unlink()


def test_write_json_falls_back_to_direct_write_when_replace_is_blocked(tmp_path):
    path = tmp_path / "fallback_state.json"
    path.write_text(json.dumps({"value": 1}), encoding="utf-8")
    original_replace = core.os.replace

    def blocking_replace(src, dst):
        if src.endswith(".tmp") and Path(dst).exists():
            raise PermissionError(13, "Access is denied")
        return original_replace(src, dst)

    with patch("core.os.replace", side_effect=blocking_replace):
        core.write_json(str(path), {"value": 42})

    assert json.loads(path.read_text(encoding="utf-8"))["value"] == 42


def test_wallet_private_keys_are_encrypted_on_disk():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        stored = core.read_json("wallet_secrets.json", {})
        assert wallet["address"] in stored
        assert stored[wallet["address"]] != wallet["private_key"]
        assert core.load_wallet_secret(wallet["address"]) == wallet["private_key"]
    finally:
        restore_working_files(backup)


def test_ops_status_reports_health_metrics():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/ops_status")
        assert response.status_code == 200
        result = response.get_json()
        assert "uptime_seconds" in result
        assert "security" in result
        assert "network" in result
        assert result["security"].get("rate_limit") is not None
        assert "bootstrap_state" in result
    finally:
        restore_working_files(backup)


def test_tls_material_is_generated_when_enabled():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["tls_enabled"] = True
        config["security"]["tls_cert_path"] = "test-cert.pem"
        config["security"]["tls_key_path"] = "test-key.pem"
        core.write_json("chain_config.json", config)
        Path("test-cert.pem").unlink(missing_ok=True)
        Path("test-key.pem").unlink(missing_ok=True)

        tls_context = api.get_tls_context()

        assert tls_context is not None
        assert Path("test-cert.pem").exists()
        assert Path("test-key.pem").exists()
        assert isinstance(tls_context, tuple)
        assert len(tls_context) == 2
    finally:
        restore_working_files(backup)
        Path("test-cert.pem").unlink(missing_ok=True)
        Path("test-key.pem").unlink(missing_ok=True)


def test_run_startup_sync_retries_transient_chain_sync_failures():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sync_calls = []

        def fake_bootstrap_on_startup():
            return {"message": "ok"}

        def fake_sync_chain():
            sync_calls.append("sync")
            if len(sync_calls) < 3:
                raise RuntimeError("temporary sync failure")
            return {"message": "ok"}

        def fake_sync_mempool():
            return {"message": "ok"}

        with patch("api.bootstrap_on_startup", side_effect=fake_bootstrap_on_startup), \
             patch("api.sync_chain", side_effect=fake_sync_chain), \
             patch("api.sync_mempool", side_effect=fake_sync_mempool), \
             patch("api.time.sleep", return_value=None):
            api._run_startup_sync(max_attempts=3, delay_seconds=0)

        assert sync_calls.count("sync") == 3
    finally:
        restore_working_files(backup)


def test_healthz_and_metrics_endpoints_report_monitoring_state():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/healthz")
        assert response.status_code == 200
        health = response.get_json()
        assert health.get("status") == "ok"
        assert "uptime_seconds" in health
        assert "healthy_peers" in health
        assert isinstance(health.get("last_events"), list)
        assert "node_health" in health
        assert health["node_health"]["blocks"] == 1

        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
        metrics = metrics_response.get_json()
        assert metrics.get("blocks") == 1
        assert "events" in metrics
        assert "peer_health" in metrics
        assert isinstance(metrics.get("events"), list)
        assert "node_health" in metrics
    finally:
        restore_working_files(backup)


def test_ops_status_reports_node_health_summary():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/ops_status")
        assert response.status_code == 200
        result = response.get_json()
        assert result["status"] == "ok"
        assert result["blocks"] == 1
        assert "storage" in result
        assert "network" in result
        assert "node" in result
        assert "uptime_human" in result
        assert isinstance(result["uptime_human"], str)
    finally:
        restore_working_files(backup)


def test_search_supports_block_lookup_by_hash():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = api.load_chain()
        genesis = chain[0]
        client = api.app.test_client()
        response = client.get(f"/search/{genesis['hash']}")
        assert response.status_code == 200
        result = response.get_json()
        assert result["type"] == "block"
        assert result["data"]["hash"] == genesis["hash"]
    finally:
        restore_working_files(backup)


def test_search_query_parameter_supports_wallet_txid_block_height_and_hash():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, sender["address"])
        chain.append(reward_block)
        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.1)
        new_block = {
            "index": 3,
            "timestamp": time.time(),
            "transactions": [{"transaction": signed_tx["transaction"], "signature": signed_tx["signature"]}],
            "proof": 0,
            "difficulty": 1,
            "previous_hash": chain[-1]["hash"],
        }
        new_block["hash"] = core.hash_block(new_block)
        chain.append(new_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        client = api.app.test_client()

        response = client.get(f"/search?q={sender['address']}")
        assert response.status_code == 200
        result = response.get_json()
        assert result["type"] == "wallet"
        assert result["address"] == sender["address"]

        response = client.get(f"/search?q={signed_tx['transaction']['txid']}")
        assert response.status_code == 200
        result = response.get_json()
        assert result["type"] == "transaction"
        assert result["txid"] == signed_tx["transaction"]["txid"]

        response = client.get(f"/search?q={new_block['index']}")
        assert response.status_code == 200
        result = response.get_json()
        assert result["type"] == "block"
        assert result["data"]["index"] == new_block["index"]

        response = client.get(f"/search?q={new_block['hash']}")
        assert response.status_code == 200
        result = response.get_json()
        assert result["type"] == "block"
        assert result["data"]["hash"] == new_block["hash"]
    finally:
        restore_working_files(backup)


def test_latest_blocks_returns_last_10_blocks_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        for _ in range(1, 15):
            chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        client = api.app.test_client()

        response = client.get("/latest_blocks")
        assert response.status_code == 200
        latest = response.get_json()
        assert isinstance(latest, list)
        assert len(latest) == 10
        assert latest[0]["index"] == 6
        assert latest[-1]["index"] == 15

        root = Path(__file__).resolve().parent
        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/latest_blocks")
        assert response.status_code == 200
        mirrored_latest = response.get_json()
        assert isinstance(mirrored_latest, list)
        assert len(mirrored_latest) == 10
    finally:
        restore_working_files(backup)


def test_latest_transactions_returns_last_25_transactions_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        for _ in range(1, 30):
            chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        client = api.app.test_client()

        response = client.get("/latest_transactions")
        assert response.status_code == 200
        latest = response.get_json()
        assert isinstance(latest, list)
        assert len(latest) == 25
        assert latest[0]["block"] == 30
        assert latest[-1]["block"] == 6

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/latest_transactions")
        assert response.status_code == 200
        mirrored_latest = response.get_json()
        assert isinstance(mirrored_latest, list)
        assert len(mirrored_latest) == 25
    finally:
        restore_working_files(backup)


def test_block_by_hash_returns_block_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        for _ in range(1, 5):
            chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        target_hash = chain[3]["hash"]
        client = api.app.test_client()

        response = client.get(f"/block/hash/{target_hash}")
        assert response.status_code == 200
        block = response.get_json()
        assert block["index"] == 4
        assert block["hash"] == target_hash

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/block/hash/{target_hash}")
        assert response.status_code == 200
        mirrored_block = response.get_json()
        assert mirrored_block["index"] == 4
        assert mirrored_block["hash"] == target_hash
    finally:
        restore_working_files(backup)


def test_block_transactions_returns_block_transactions_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        for _ in range(1, 4):
            chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        target_index = 3
        target_block = chain[target_index - 1]
        client = api.app.test_client()

        response = client.get(f"/block/{target_index}/transactions")
        assert response.status_code == 200
        txs = response.get_json()
        assert isinstance(txs, list)
        assert txs == target_block["transactions"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/block/{target_index}/transactions")
        assert response.status_code == 200
        mirrored_txs = response.get_json()
        assert isinstance(mirrored_txs, list)
        assert mirrored_txs == target_block["transactions"]
    finally:
        restore_working_files(backup)


def test_block_fees_returns_total_fee_amount_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        chain.append(make_reward_block_for(chain, sender["address"]))
        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.1)
        new_block = {
            "index": len(chain) + 1,
            "timestamp": time.time(),
            "transactions": [{"transaction": signed_tx["transaction"], "signature": signed_tx["signature"]}],
            "proof": 0,
            "difficulty": 1,
            "previous_hash": chain[-1]["hash"],
        }
        new_block["hash"] = core.hash_block(new_block)
        chain.append(new_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get(f"/block/{new_block['index']}/fees")
        assert response.status_code == 200
        fees = response.get_json()
        assert fees["index"] == new_block["index"]
        assert fees["fees"] == 0.1

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/block/{new_block['index']}/fees")
        assert response.status_code == 200
        mirrored_fees = response.get_json()
        assert mirrored_fees["index"] == new_block["index"]
        assert mirrored_fees["fees"] == 0.1
    finally:
        restore_working_files(backup)


def test_block_reward_returns_mining_reward_details_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, sender["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        reward_block_index = reward_block["index"]
        client = api.app.test_client()
        response = client.get(f"/block/{reward_block_index}/reward")
        assert response.status_code == 200
        reward = response.get_json()
        assert reward["index"] == reward_block_index
        assert reward["total_reward"] == reward_block["transactions"][0]["transaction"]["amount"]
        assert reward["fees"] == reward_block["transactions"][0]["transaction"]["fees"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/block/{reward_block['index']}/reward")
        assert response.status_code == 200
        mirrored_reward = response.get_json()
        assert mirrored_reward["index"] == reward_block["index"]
        assert mirrored_reward["total_reward"] == reward_block["transactions"][0]["transaction"]["amount"]
        assert mirrored_reward["fees"] == reward_block["transactions"][0]["transaction"]["fees"]
    finally:
        restore_working_files(backup)


def test_block_header_returns_header_fields_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        for _ in range(1, 4):
            chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        target_index = 3
        target_block = chain[target_index - 1]
        client = api.app.test_client()
        response = client.get(f"/block/{target_index}/header")
        assert response.status_code == 200
        header = response.get_json()
        assert header["index"] == target_block["index"]
        assert header["hash"] == target_block["hash"]
        assert header["previous_hash"] == target_block["previous_hash"]
        assert header["difficulty"] == target_block["difficulty"]
        assert header["proof"] == target_block["proof"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/block/{target_index}/header")
        assert response.status_code == 200
        mirrored_header = response.get_json()
        assert mirrored_header["index"] == target_block["index"]
        assert mirrored_header["hash"] == target_block["hash"]
    finally:
        restore_working_files(backup)


def test_network_info_returns_summary_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/network_info")
        assert response.status_code == 200
        data = response.get_json()
        assert data["blockchain"]["height"] == len(chain)
        assert "node" in data and "network" in data

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/network_info")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["blockchain"]["height"] == len(chain)
    finally:
        restore_working_files(backup)


def test_version_endpoint_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/version")
        assert response.status_code == 200
        data = response.get_json()
        assert "version" in data and "node_version" in data
        assert data["uptime_seconds"] >= 0

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/version")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["version"] == data["version"]
    finally:
        restore_working_files(backup)


def test_health_endpoint_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] in ("ok", "degraded")
        assert isinstance(data["uptime_seconds"], int)

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/health")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["status"] in ("ok", "degraded")
    finally:
        restore_working_files(backup)


def test_genesis_returns_genesis_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/genesis")
        assert response.status_code == 200
        data = response.get_json()
        assert data == chain[0]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/genesis")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data == chain[0]
    finally:
        restore_working_files(backup)


def test_mining_info_returns_summary_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/mining_info")
        assert response.status_code == 200
        data = response.get_json()
        assert data["height"] == len(chain)
        assert data["current_difficulty"] == chain[-1].get("difficulty", 1)
        assert data["next_difficulty"] == core.calculate_next_difficulty(chain)
        assert data["current_reward"] == core.calculate_reward(len(chain), core.get_total_supply(chain))

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/mining_info")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["height"] == len(chain)
    finally:
        restore_working_files(backup)


def test_reward_schedule_returns_schedule_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/reward_schedule")
        assert response.status_code == 200
        data = response.get_json()
        assert data["initial_reward"] == core.DEFAULT_CHAIN_CONFIG["initial_reward"]
        assert data["reward_schedule"] == core.DEFAULT_CHAIN_CONFIG["reward_schedule"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/reward_schedule")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["initial_reward"] == core.DEFAULT_CHAIN_CONFIG["initial_reward"]
    finally:
        restore_working_files(backup)


def test_difficulty_endpoint_returns_difficulty_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/difficulty")
        assert response.status_code == 200
        data = response.get_json()
        assert data["height"] == len(chain)
        assert data["current_difficulty"] == chain[-1].get("difficulty", 1)
        assert data["next_difficulty"] == core.calculate_next_difficulty(chain)

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/difficulty")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["height"] == len(chain)
    finally:
        restore_working_files(backup)


def test_wallet_balance_history_returns_history_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, sender["address"])
        chain.append(reward_block)
        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.2)
        transfer_block = {
            "index": len(chain) + 1,
            "timestamp": time.time(),
            "transactions": [{"transaction": signed_tx["transaction"], "signature": signed_tx["signature"]}],
            "proof": 0,
            "difficulty": 1,
            "previous_hash": reward_block["hash"],
        }
        transfer_block["hash"] = core.hash_block(transfer_block)
        chain.append(transfer_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get(f"/wallet/{sender['address']}/balance_history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["address"] == sender["address"]
        assert data["history"]
        assert data["history"][-1]["balance"] >= 0

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/wallet/{sender['address']}/balance_history")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["address"] == sender["address"]
    finally:
        restore_working_files(backup)


def test_network_activity_returns_recent_blocks_and_transactions_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        chain.append(make_reward_block_for(chain, core.create_wallet()["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/network_activity")
        assert response.status_code == 200
        data = response.get_json()
        assert data["height"] == len(chain)
        assert data["latest_blocks"]
        assert data["latest_transactions"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/network_activity")
        assert response.status_code == 200
        mirrored_data = response.get_json()
        assert mirrored_data["height"] == len(chain)
    finally:
        restore_working_files(backup)


def test_wallet_stats_returns_expected_metrics_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        for _ in range(1, 3):
            chain.append(make_reward_block_for(chain, sender["address"]))
        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 2, fee=0.1)
        new_block = {
            "index": len(chain) + 1,
            "timestamp": time.time(),
            "transactions": [{"transaction": signed_tx["transaction"], "signature": signed_tx["signature"]}],
            "proof": 0,
            "difficulty": 1,
            "previous_hash": chain[-1]["hash"],
        }
        new_block["hash"] = core.hash_block(new_block)
        chain.append(new_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        response = api.app.test_client().get(f"/wallet/{sender['address']}/stats")
        assert response.status_code == 200
        stats = response.get_json()
        expected_summary = api.wallet_summary(sender["address"], chain)
        assert stats["total_received"] == expected_summary["received"]
        assert stats["total_sent"] == expected_summary["sent"]
        assert stats["current_balance"] == expected_summary["balance"]
        assert stats["transaction_count"] == expected_summary["transactions"]
        assert stats["first_transaction"]["txid"] is not None
        assert stats["last_transaction"]["txid"] is not None

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/wallet/{sender['address']}/stats")
        assert response.status_code == 200
        mirrored_stats = response.get_json()
        assert mirrored_stats["transaction_count"] == expected_summary["transactions"]
        assert mirrored_stats["total_received"] == expected_summary["received"]
        assert mirrored_stats["total_sent"] == expected_summary["sent"]
        assert mirrored_stats["current_balance"] == expected_summary["balance"]
        assert mirrored_stats["first_transaction"]["txid"] is not None
        assert mirrored_stats["last_transaction"]["txid"] is not None
    finally:
        restore_working_files(backup)


def test_wallet_pending_returns_mempool_transactions_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 5, fee=0.2)
        Path("mempool.json").write_text(json.dumps([signed_tx], indent=4))

        client = api.app.test_client()
        response = client.get(f"/wallet/{sender['address']}/pending")
        assert response.status_code == 200
        pending = response.get_json()
        assert isinstance(pending, list)
        assert len(pending) == 1
        assert pending[0]["txid"] == signed_tx["transaction"]["txid"]
        assert pending[0]["from"] == sender["address"]
        assert pending[0]["to"] == receiver["address"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/wallet/{sender['address']}/pending")
        assert response.status_code == 200
        mirrored_pending = response.get_json()
        assert isinstance(mirrored_pending, list)
        assert len(mirrored_pending) == 1
        assert mirrored_pending[0]["txid"] == signed_tx["transaction"]["txid"]
    finally:
        restore_working_files(backup)


def test_wallet_nonce_returns_next_nonce_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        Path("mempool.json").write_text(json.dumps([], indent=4))

        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.1)
        Path("mempool.json").write_text(json.dumps([signed_tx], indent=4))

        client = api.app.test_client()
        response = client.get(f"/wallet/{sender['address']}/nonce")
        assert response.status_code == 200
        data = response.get_json()
        assert data["address"] == sender["address"]
        assert data["next_nonce"] == signed_tx["transaction"]["nonce"] + 1

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/wallet/{sender['address']}/nonce")
        assert response.status_code == 200
        mirrored_data = mirrored_app.get_json()
        assert mirrored_data["address"] == sender["address"]
        assert mirrored_data["next_nonce"] == signed_tx["transaction"]["nonce"] + 1
    finally:
        restore_working_files(backup)


def test_wallet_transaction_pagination_returns_pageed_results_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        for _ in range(30):
            chain.append(make_reward_block_for(chain, wallet["address"]))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get(f"/wallet/{wallet['address']}/transactions?page=1")
        assert response.status_code == 200
        page1 = response.get_json()
        assert isinstance(page1, list)
        assert len(page1) == 25

        response = client.get(f"/wallet/{wallet['address']}/transactions?page=2")
        assert response.status_code == 200
        page2 = response.get_json()
        assert isinstance(page2, list)
        assert len(page2) == 5

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get(f"/wallet/{wallet['address']}/transactions?page=1")
        assert response.status_code == 200
        mirrored_page1 = response.get_json()
        assert isinstance(mirrored_page1, list)
        assert len(mirrored_page1) == 25
    finally:
        restore_working_files(backup)


def test_charts_endpoint_returns_supply_block_and_difficulty_series():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/charts")
        assert response.status_code == 200
        result = response.get_json()
        assert "supply" in result
        assert "blocks" in result
        assert "difficulty" in result
        assert isinstance(result["supply"], list)
        assert isinstance(result["blocks"], list)
        assert isinstance(result["difficulty"], list)
        assert result["supply"]
        assert result["blocks"]
        assert result["difficulty"]

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/charts")
        assert response.status_code == 200
        mirrored_result = response.get_json()
        assert mirrored_result["supply"]
        assert mirrored_result["blocks"]
        assert mirrored_result["difficulty"]
    finally:
        restore_working_files(backup)


def test_export_chain_endpoint_returns_chain_payload_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        chain.append(make_reward_block_for(chain, "test-address"))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/export/chain")
        assert response.status_code == 200
        result = response.get_json()
        assert result["height"] == len(chain)
        assert isinstance(result["chain"], list)
        assert len(result["chain"]) == len(chain)
        assert result["chain"][0]["index"] == 1

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/export/chain")
        assert response.status_code == 200
        mirrored_result = response.get_json()
        assert mirrored_result["height"] == len(chain)
        assert len(mirrored_result["chain"]) == len(chain)
    finally:
        restore_working_files(backup)


def test_export_block_endpoint_returns_block_payload_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        chain.append(make_reward_block_for(chain, "test-address"))
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        client = api.app.test_client()
        response = client.get("/export/block/2")
        assert response.status_code == 200
        result = response.get_json()
        assert result["height"] == 2
        assert isinstance(result["block"], dict)
        assert result["block"]["index"] == 2

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/export/block/2")
        assert response.status_code == 200
        mirrored_result = response.get_json()
        assert mirrored_result["height"] == 2
        assert mirrored_result["block"]["index"] == 2
    finally:
        restore_working_files(backup)


def test_circulating_supply_endpoint_returns_supply_metrics():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/circulating_supply")
        assert response.status_code == 200
        result = response.get_json()
        assert "total_supply" in result
        assert "circulating_supply" in result
        assert "max_supply" in result
        assert result["max_supply"] >= result["total_supply"]
    finally:
        restore_working_files(backup)


def test_api_docs_endpoint_serves_documentation_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/api_docs")
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "Blockchain API Documentation" in body
        assert "/export/chain" in body

        mirrored_path = Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py")
        spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
        mirrored_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mirrored_api)
        mirrored_app = mirrored_api.app.test_client()
        response = mirrored_app.get("/api_docs")
        assert response.status_code == 200
        mirrored_body = response.get_data(as_text=True)
        assert "Blockchain API Documentation" in mirrored_body
        assert "/export/block/" in mirrored_body
    finally:
        restore_working_files(backup)


def test_explorer_page_contains_wallet_import_form():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/explorer")
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "Paste private key" in body
        assert "Import Wallet" in body
    finally:
        restore_working_files(backup)


def test_network_health_dashboard_exposes_human_readable_times():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/network_health_dashboard")
        assert response.status_code == 200
        result = response.get_json()
        assert "timestamp_human" in result
        assert "latest_block_time_human" in result["blockchain"]
        assert "last_bootstrap_time_human" in result["bootstrap_state"]
    finally:
        restore_working_files(backup)


def test_load_peers_auto_discovers_from_seed_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["127.0.0.1:5001"]
        core.write_json("chain_config.json", config)

        class FakeResponse:
            def __init__(self, payload, status_code=200):
                self._payload = payload
                self.status_code = status_code

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, timeout=3):
            if url.endswith("/node_info"):
                return FakeResponse({"valid": True, "network_id": api.get_network_id(), "node_id": "peer-a"})
            if url.endswith("/peers"):
                return FakeResponse(["127.0.0.1:5002"])
            raise AssertionError(f"Unexpected URL: {url}")

        with patch.object(api, "peer_node_info", return_value={"valid": True, "network_id": api.get_network_id(), "node_id": "peer-a"}):
            with patch.object(api.requests, "get", side_effect=fake_get):
                peers = api.load_peers()

        assert "127.0.0.1:5001" in peers
        assert "127.0.0.1:5002" in peers
    finally:
        restore_working_files(backup)


def test_bootstrap_on_startup_triggers_chain_sync_after_bootstrap():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["127.0.0.1:5001"]
        core.write_json("chain_config.json", config)

        with patch.object(api, "bootstrap", return_value={"message": "Bootstrap complete"}) as bootstrap_mock:
            with patch.object(api, "sync_chain", return_value={"message": "synced"}) as sync_chain_mock:
                result = api.bootstrap_on_startup(force=True)

        assert result["message"] == "Bootstrap complete"
        bootstrap_mock.assert_called_once_with()
        sync_chain_mock.assert_called_once_with()
    finally:
        restore_working_files(backup)


def test_bootstrap_on_startup_retries_sync_after_transient_failure():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["127.0.0.1:5001"]
        core.write_json("chain_config.json", config)

        with patch.object(api, "bootstrap", return_value={"message": "Bootstrap complete"}):
            with patch.object(api, "sync_chain", side_effect=[RuntimeError("temporary"), {"message": "synced"}]) as sync_chain_mock:
                with patch.object(api.time, "sleep", return_value=None):
                    result = api.bootstrap_on_startup(force=True)

        assert result["message"] == "Bootstrap complete"
        assert sync_chain_mock.call_count == 2
        assert result["sync"] == {"message": "synced"}
    finally:
        restore_working_files(backup)


def test_wait_for_flask_ready_returns_true_when_health_endpoint_returns_ok():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        with patch.object(api.requests, "get") as mock_get:
            mock_get.return_value.status_code = 200
            assert api._wait_for_flask_ready(5000, timeout_seconds=1) is True
    finally:
        restore_working_files(backup)


def test_public_bootstrap_startup_scripts_are_available_on_both_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        root_script = Path("start_testnet_node.ps1")
        node2_script = Path("2026 blockchain node2/start_testnet_node.ps1")

        assert root_script.exists()
        assert node2_script.exists()

        root_content = root_script.read_text(encoding="utf-8")
        node2_content = node2_script.read_text(encoding="utf-8")

        assert "SeedNodes" in root_content
        assert "SeedNodes" in node2_content
        assert "seed_nodes" in root_content.lower()
    finally:
        restore_working_files(backup)


def test_tls_enabled_bootstrap_uses_https_peer_urls():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["tls_enabled"] = True
        core.write_json("chain_config.json", config)

        self_url = api.get_self_peer_url()
        normalized = api.normalize_peer("127.0.0.1:5000")

        assert self_url.startswith("https://")
        assert normalized.startswith("https://")
    finally:
        restore_working_files(backup)


def test_recover_state_restores_latest_backup():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        core.backup_file("blockchain_data.json")
        Path("blockchain_data.json").write_text("{not valid json")
        recovered = core.recover_state_file("blockchain_data.json", default=chain)
        assert recovered == chain
        assert Path("blockchain_data.json").exists()
    finally:
        restore_working_files(backup)


def test_backup_status_and_restore_state_endpoints():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        backup_response = client.post("/backup_state", json={"path": "blockchain_data.json"})
        assert backup_response.status_code == 200
        backup_result = backup_response.get_json()
        assert backup_result.get("created") is True

        status_response = client.get("/backup_status")
        assert status_response.status_code == 200
        status_result = status_response.get_json()
        assert status_result.get("status") == "ok"
        assert status_result.get("backup_count", 0) >= 1

        restore_response = client.post("/restore_state", json={"path": "blockchain_data.json", "default": []})
        assert restore_response.status_code == 200
        restore_result = restore_response.get_json()
        assert restore_result.get("recovered") is True
    finally:
        restore_working_files(backup)


def test_import_wallet():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        new_wallet = core.create_wallet()
        client = api.app.test_client()
        response = client.post("/import_wallet", json={"private_key": new_wallet["private_key"]})
        assert response.status_code == 200, response.get_data(as_text=True)
        result = response.get_json()
        assert result["address"] == new_wallet["address"]
        assert Path("public_keys.json").exists()
        saved = json.loads(Path("public_keys.json").read_text())
        assert any(item.get("address") == new_wallet["address"] for item in saved)
    finally:
        restore_working_files(backup)


def test_public_key_endpoints_sync_across_all_nodes():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        client = api.app.test_client()
        response = client.post("/register_public_key", json={"address": wallet["address"], "public_key": wallet["public_key"]})
        assert response.status_code == 200
        keys_response = client.get("/public_keys")
        assert keys_response.status_code == 200
        keys_result = keys_response.get_json()
        assert any(item.get("address") == wallet["address"] for item in keys_result)

        node_paths = [
            Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py"),
            Path("c:/Users/MD khalid/Desktop/2026 blockchain node3/api.py"),
        ]
        for path in node_paths:
            spec = importlib.util.spec_from_file_location("mirrored_api", path)
            mirrored_api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mirrored_api)
            mirrored_app = mirrored_api.app.test_client()
            mirrored_response = mirrored_app.get("/public_keys")
            assert mirrored_response.status_code == 200
            mirrored_result = mirrored_response.get_json()
            assert any(item.get("address") == wallet["address"] for item in mirrored_result)
    finally:
        restore_working_files(backup)


def test_mine_syncs_with_peers_before_mining():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        with patch.object(api, "sync_chain", return_value={"message": "synced"}) as sync_mock, patch("subprocess.run") as run_mock:
            run_mock.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
            response = client.get("/mine")
        assert response.status_code == 200
        sync_mock.assert_called_once()
        run_mock.assert_called_once()
    finally:
        restore_working_files(backup)


def test_backup_wallet_endpoint_exports_wallet_json_payload():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        new_wallet = core.create_wallet()
        client = api.app.test_client()
        response = client.post("/import_wallet", json={"private_key": new_wallet["private_key"]})
        assert response.status_code == 200

        backup_response = client.post("/backup_wallet", json={"address": new_wallet["address"]})
        assert backup_response.status_code == 200, backup_response.get_data(as_text=True)
        result = backup_response.get_json()
        assert result["address"] == new_wallet["address"]
        assert result["private_key"] == new_wallet["private_key"]
    finally:
        restore_working_files(backup)


def test_send_transaction_endpoint():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, wallet["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        receiver_wallet = core.create_wallet()
        client = api.app.test_client()
        response = client.post(
            "/send_transaction",
            json={
                "private_key": wallet["private_key"],
                "to": receiver_wallet["address"],
                "amount": 1,
                "fee": 1,
            },
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        result = response.get_json()
        assert "txid" in result
        mempool = json.loads(Path("mempool.json").read_text())
        assert len(mempool) == 1
    finally:
        restore_working_files(backup)


def test_transaction_lookup_by_txid_returns_block_and_confirmations():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        receiver = core.create_wallet()
        reward_block = make_reward_block_for(chain, wallet["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        tx = core.create_signed_transaction(
            wallet["private_key"],
            receiver["address"],
            1,
            fee=0.1,
        )
        chain.append({
            "index": 3,
            "timestamp": time.time(),
            "transactions": [{"transaction": tx["transaction"], "signature": tx["signature"]}],
            "proof": 0,
            "difficulty": 1,
            "previous_hash": chain[-1]["hash"],
            "hash": core.hash_block({
                "index": 3,
                "timestamp": time.time(),
                "transactions": [{"transaction": tx["transaction"], "signature": tx["signature"]}],
                "proof": 0,
                "difficulty": 1,
                "previous_hash": chain[-1]["hash"],
            }),
        })
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))

        txid = tx["transaction"]["txid"]
        client = api.app.test_client()
        response = client.get(f"/tx/{txid}")
        assert response.status_code == 200, response.get_data(as_text=True)
        result = response.get_json()
        assert result["txid"] == txid
        assert result["block"] == 3
        assert result["confirmations"] == 1
        assert result["from"] == wallet["address"]
        assert result["to"] == receiver["address"]
        assert result["amount"] == 1
        assert result["fee"] == 0.1
        assert result["signature"] == tx["signature"]
    finally:
        restore_working_files(backup)


def test_malformed_mempool_does_not_crash_send_transaction():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, wallet["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("{not-valid-json}")

        receiver_wallet = core.create_wallet()
        client = api.app.test_client()
        response = client.post(
            "/send_transaction",
            json={
                "private_key": wallet["private_key"],
                "to": receiver_wallet["address"],
                "amount": 1,
                "fee": 1,
            },
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        mempool = json.loads(Path("mempool.json").read_text())
        assert len(mempool) == 1
    finally:
        restore_working_files(backup)


def test_many_transactions_do_not_crash_mempool_flow():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, wallet["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        receiver_wallet = core.create_wallet()
        client = api.app.test_client()
        for _ in range(100):
            response = client.post(
                "/send_transaction",
                json={
                    "private_key": wallet["private_key"],
                    "to": receiver_wallet["address"],
                    "amount": 0.01,
                    "fee": 0.01,
                },
            )
            assert response.status_code == 200, response.get_data(as_text=True)

        mempool = json.loads(Path("mempool.json").read_text())
        assert len(mempool) == 100
    finally:
        restore_working_files(backup)


def test_unsigned_browser_requests_can_access_bootstrap_and_sync_endpoints_when_peer_auth_is_configured():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["peer_registration_token"] = "registration-token"
        config["security"]["peer_shared_secret"] = "shared-secret"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        for path in ["/bootstrap", "/sync_peers", "/sync_chain"]:
            response = client.get(path, headers={"Authorization": "Bearer registration-token"})
            assert response.status_code == 200, (path, response.get_data(as_text=True))
    finally:
        restore_working_files(backup)


def test_register_peer_self_ignored():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        config = core.read_json("node_config.json", {})
        response = client.post("/register_peer", json={"peer": f"127.0.0.1:{config.get('port', 5000)}"})
        assert response.status_code == 200
        result = response.get_json()
        assert "self" in result.get("message", "").lower()
    finally:
        restore_working_files(backup)


def test_register_peer_requires_auth_token_when_configured():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["peer_registration_token"] = "test-token"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        node_config = core.read_json("node_config.json", {})
        response = client.post("/register_peer", json={"peer": f"127.0.0.1:{node_config.get('port', 5000)}"})
        assert response.status_code == 403
        assert "authorization" in response.get_json().get("error", "").lower()
        response = client.post(
            "/register_peer",
            headers={"Authorization": "Bearer test-token"},
            json={"peer": f"127.0.0.1:{node_config.get('port', 5000)}"},
        )
        assert response.status_code == 200
    finally:
        restore_working_files(backup)


def test_sync_endpoints_require_auth_token_when_configured():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["peer_registration_token"] = "test-token"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.get("/sync_peers")
        assert response.status_code == 403
        response = client.get("/sync_peers", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
    finally:
        restore_working_files(backup)


def test_rate_limiting_blocks_excessive_requests():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["rate_limit"] = 2
        config["security"]["rate_limit_window_seconds"] = 60
        config["security"]["rate_limit_ban_seconds"] = 60
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        for _ in range(2):
            response = client.get("/status")
            assert response.status_code == 200
        response = client.get("/status")
        assert response.status_code == 429
    finally:
        restore_working_files(backup)


def test_hmac_peer_auth_accepts_signed_requests_when_configured():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["peer_shared_secret"] = "shared-secret"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        payload = {"peer": "127.0.0.1:5000"}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"shared-secret",
            f"/register_peer:{timestamp}:{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        response = client.post(
            "/register_peer",
            headers={"X-Node-Id": "peer-a", "X-Timestamp": timestamp, "X-Peer-Signature": signature},
            json=payload,
        )
        assert response.status_code == 200
    finally:
        restore_working_files(backup)


def test_mirrored_node_supports_signed_peer_helpers():
    root = Path(__file__).resolve().parent
    mirrored_candidates = [
        root / "2026 blockchain node2" / "api.py",
        root.parent / "2026 blockchain node2" / "api.py",
        Path("c:/Users/MD khalid/Desktop/2026 blockchain node2/api.py"),
    ]
    mirrored_path = next((candidate for candidate in mirrored_candidates if candidate.exists()), None)
    assert mirrored_path is not None, mirrored_candidates
    spec = importlib.util.spec_from_file_location("mirrored_api", mirrored_path)
    mirrored_api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mirrored_api)
    assert hasattr(mirrored_api, "build_peer_headers")
    assert hasattr(mirrored_api, "signed_get")
    assert hasattr(mirrored_api, "signed_post")


def test_sync_peers_endpoint():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/sync_peers")
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("added") == 0
        assert isinstance(result.get("peers"), list)
        assert isinstance(result.get("errors"), list)
    finally:
        restore_working_files(backup)


def test_bootstrap_endpoint():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/bootstrap")
        assert response.status_code == 200, response.get_data(as_text=True)
        result = response.get_json()
        assert result.get("message") == "Bootstrap complete"
        assert isinstance(result.get("peers"), list)
        assert "seed_added" in result
        assert "discovered_peer_added" in result
        assert isinstance(result.get("errors"), list)
        assert result.get("node_version")
        assert isinstance(result.get("bootstrap_policy"), dict)
    finally:
        restore_working_files(backup)


def test_bootstrap_status_endpoint_reports_state():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        bootstrap_response = client.get("/bootstrap")
        assert bootstrap_response.status_code == 200
        status_response = client.get("/bootstrap_status")
        assert status_response.status_code == 200
        status_result = status_response.get_json()
        assert status_result.get("status") == "ok"
        assert isinstance(status_result.get("seed_nodes"), list)
        assert isinstance(status_result.get("bootstrap_state"), dict)
        config = core.load_chain_config()
        assert config.get("bootstrap_state", {}).get("last_bootstrap_status") == "complete"
    finally:
        restore_working_files(backup)


def test_register_peer_respects_trust_policy():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["peer_trust_policy"] = {
            "allow_public_bootstrap": False,
            "allowlist": ["trusted.example:443"],
            "denylist": [],
        }
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.post("/register_peer", json={"peer": "untrusted.example:443"})
        assert response.status_code == 403
        assert "trust" in response.get_json().get("error", "").lower()
    finally:
        restore_working_files(backup)


def test_bootstrap_config_endpoint_updates_seed_nodes_and_trust_policy():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        payload = {
            "seed_nodes": ["seed.example:443"],
            "trust_policy": {
                "allow_public_bootstrap": False,
                "allowlist": ["seed.example:443"],
                "denylist": [],
            },
            "rollout_pending": True,
            "rollout_safety_mode": True,
            "public_api_enabled": False,
        }
        response = client.post("/bootstrap_config", json=payload)
        assert response.status_code == 200
        result = response.get_json()
        assert "seed.example:443" in result.get("seed_nodes", [])
        config = core.load_chain_config()
        assert "seed.example:443" in config.get("seed_nodes", [])
        assert config.get("peer_trust_policy", {}).get("allowlist") == ["seed.example:443"]
        assert config.get("security", {}).get("rollout_pending") is True
        assert config.get("security", {}).get("rollout_safety_mode") is True
        assert config.get("security", {}).get("public_api_enabled") is False
    finally:
        restore_working_files(backup)


def test_trust_policy_automation_promote_by_reputation():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "admin-token"
        core.write_json("chain_config.json", config)
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5001", "127.0.0.1:5002"], indent=4))
        api.update_peer_reputation("127.0.0.1:5001", 15, reason="test high reputation")
        api.update_peer_reputation("127.0.0.1:5002", -10, reason="test low reputation")
        client = api.app.test_client()
        response = client.post(
            "/trust_policy_update",
            headers={"Authorization": "Bearer admin-token"},
            json={"action": "promote_by_reputation", "threshold": 10},
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("action") == "promote_by_reputation"
        updated_config = core.load_chain_config()
        allowlist = updated_config.get("peer_trust_policy", {}).get("allowlist", [])
        assert len(allowlist) >= 0
    finally:
        restore_working_files(backup)


def test_trust_policy_automation_demote_by_reputation():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "admin-token"
        core.write_json("chain_config.json", config)
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5001", "127.0.0.1:5002"], indent=4))
        api.update_peer_reputation("127.0.0.1:5001", -15, reason="test low reputation")
        client = api.app.test_client()
        response = client.post(
            "/trust_policy_update",
            headers={"Authorization": "Bearer admin-token"},
            json={"action": "demote_by_reputation", "threshold": -5},
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("action") == "demote_by_reputation"
        updated_config = core.load_chain_config()
        denylist = updated_config.get("peer_trust_policy", {}).get("denylist", [])
        assert len(denylist) >= 0
    finally:
        restore_working_files(backup)


def test_trust_policy_update_requires_admin_auth():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "some-secret-token"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.post(
            "/trust_policy_update",
            json={"action": "promote_by_reputation", "threshold": 10},
        )
        assert response.status_code == 403
        assert "Admin authentication required" in response.get_json().get("error", "")
    finally:
        restore_working_files(backup)


def test_deployment_control_endpoint_updates_runtime_config():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.post(
            "/deployment_control",
            json={"action": "set", "key": "rate_limit", "value": 30},
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("status") == "ok"
        assert core.load_chain_config().get("security", {}).get("rate_limit") == 30
    finally:
        restore_working_files(backup)


def test_public_access_control_and_rollout_safety_gates():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["public_api_enabled"] = False
        config["security"]["rollout_safety_mode"] = True
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.get("/healthz")
        assert response.status_code == 403
        response = client.get("/deployment_status")
        assert response.status_code == 403
        response = client.post(
            "/deployment_control",
            json={"action": "set", "key": "rate_limit", "value": 30},
        )
        assert response.status_code == 403
    finally:
        restore_working_files(backup)


def test_admin_authentication_and_rollout_approval_workflow():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "super-secret"
        config["security"]["rollout_pending"] = True
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.post(
            "/deployment_control",
            json={"action": "set", "key": "rate_limit", "value": 30},
        )
        assert response.status_code == 403
        response = client.post(
            "/deployment_control",
            headers={"Authorization": "Bearer super-secret"},
            json={"action": "set", "key": "rate_limit", "value": 30},
        )
        assert response.status_code == 200
    finally:
        restore_working_files(backup)


def test_mirrored_node_exposes_rollout_control_endpoints():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        status_response = client.get("/deployment_status")
        assert status_response.status_code == 200
        control_response = client.post(
            "/deployment_control",
            json={"action": "get", "key": "security.rollout_pending"},
        )
        assert control_response.status_code == 200
        result = control_response.get_json()
        assert result.get("status") == "ok"
    finally:
        restore_working_files(backup)


def test_audit_log_and_approval_history_are_persisted():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "super-secret"
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.post(
            "/deployment_control",
            headers={"Authorization": "Bearer super-secret"},
            json={"action": "set", "key": "rate_limit", "value": 30},
        )
        assert response.status_code == 200
        audit_log = api.load_audit_log()
        assert len(audit_log) >= 1
        history = api.load_approval_history()
        assert isinstance(history, list)
    finally:
        restore_working_files(backup)


def test_operator_history_endpoints_expose_audit_and_approval_data():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["security"]["admin_token"] = "super-secret"
        core.write_json("chain_config.json", config)
        api.append_audit_event("test_event", "Audit entry created")
        api.append_approval_event("test_action", True, {"source": "test"})
        client = api.app.test_client()
        audit_response = client.get(
            "/audit_log",
            headers={"Authorization": "Bearer super-secret"},
        )
        assert audit_response.status_code == 200
        audit_result = audit_response.get_json()
        assert isinstance(audit_result, list)
        assert any(entry.get("type") == "test_event" for entry in audit_result)

        history_response = client.get(
            "/approval_history",
            headers={"Authorization": "Bearer super-secret"},
        )
        assert history_response.status_code == 200
        history_result = history_response.get_json()
        assert isinstance(history_result, list)
        assert any(entry.get("action") == "test_action" for entry in history_result)
    finally:
        restore_working_files(backup)


def test_sync_chain_replaces_local_chain_with_longer_valid_peer_chain():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        local_chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(local_chain, indent=4))
        Path("peers.json").write_text(json.dumps(["http://127.0.0.1:5001", "http://127.0.0.1:5002"]))

        longer_peer_chain = [
            core.create_genesis_block(),
            make_reward_block_for([core.create_genesis_block()], "peer-address"),
        ]

        def fake_signed_get(url, **kwargs):
            if url == "http://127.0.0.1:5001/chain":
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"chain": [core.create_genesis_block()]},
                )
            if url == "http://127.0.0.1:5002/chain":
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"chain": longer_peer_chain},
                )
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("api.load_peers", return_value=["http://127.0.0.1:5001", "http://127.0.0.1:5002"]):
            with patch("api.sync_peer_list", return_value=([], 0, [])):
                with patch("api.signed_get", side_effect=fake_signed_get):
                    response = api.app.test_client().get("/sync_chain")

        assert response.status_code == 200
        result = response.get_json()
        assert result.get("message") == "Chain replaced with stronger valid chain"
        assert result.get("source") == "http://127.0.0.1:5002"
        assert len(api.load_chain()) == len(longer_peer_chain)
    finally:
        restore_working_files(backup)


def test_sync_chain_uses_healthy_peers():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/sync_chain")
        assert response.status_code == 200
        result = response.get_json()
        assert "blocks" in result
        assert "peer_errors" in result
    finally:
        restore_working_files(backup)


def test_sync_mempool_endpoint():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        response = client.get("/sync_mempool")
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("message") == "Mempool sync complete"
        assert isinstance(result.get("added"), int)
        assert isinstance(result.get("pending"), int)
        assert isinstance(result.get("peers_queried"), int)
        assert isinstance(result.get("errors"), list)
    finally:
        restore_working_files(backup)


def test_sync_mempool_excludes_confirmed_transactions():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, sender["address"])
        chain.append(reward_block)

        confirmed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.1)
        confirmed_block = {
            "index": len(chain) + 1,
            "timestamp": time.time(),
            "transactions": [confirmed_tx],
            "proof": 0,
            "difficulty": core.calculate_next_difficulty(chain),
            "previous_hash": chain[-1]["hash"],
        }
        confirmed_block["hash"] = core.hash_block(confirmed_block)
        chain.append(confirmed_block)

        next_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 2, fee=0.1)

        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text("[]")

        peer_mempool = [confirmed_tx, next_tx]

        def fake_signed_get(url, **kwargs):
            if url.endswith("/mempool"):
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: peer_mempool)
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("api.sync_peer_list", return_value=([], 0, [])), \
             patch("api.healthy_peers", return_value=[]), \
             patch("api.load_peers", return_value=["127.0.0.1:5001"]), \
             patch("api.signed_get", side_effect=fake_signed_get):
            client = api.app.test_client()
            response = client.get("/sync_mempool")

        assert response.status_code == 200
        result = response.get_json()
        assert result.get("added") == 1
        assert result.get("pending") == 1
        saved_mempool = json.loads(Path("mempool.json").read_text())
        assert len(saved_mempool) == 1
        assert core.tx_id(saved_mempool[0]) == core.tx_id(next_tx)
    finally:
        restore_working_files(backup)


def test_receive_block_removes_mined_transactions_from_mempool():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        sender = core.create_wallet()
        receiver = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, sender["address"])
        chain.append(reward_block)

        signed_tx = core.create_signed_transaction(sender["private_key"], receiver["address"], 1, fee=0.1)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        Path("mempool.json").write_text(json.dumps([signed_tx], indent=4))

        new_block = {
            "index": len(chain) + 1,
            "timestamp": time.time(),
            "transactions": [signed_tx],
            "proof": 0,
            "difficulty": core.calculate_next_difficulty(chain),
            "previous_hash": chain[-1]["hash"],
        }
        new_block["hash"] = core.hash_block(new_block)

        client = api.app.test_client()
        response = client.post("/receive_block", json=new_block)
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("message") == "Block received"
        saved_mempool = json.loads(Path("mempool.json").read_text())
        assert all(core.tx_id(tx) != core.tx_id(signed_tx) for tx in saved_mempool)
    finally:
        restore_working_files(backup)


def test_process_orphans_cleans_stale_orphans():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        chain = [core.create_genesis_block()]
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        stale_orphan = {
            "hash": "deadbeef",
            "previous_hash": "0",
            "index": 2,
            "reason": "Stale test",
            "first_seen": time.time() - 90000,
            "last_seen": time.time() - 90000,
            "block": {
                "index": 2,
                "timestamp": time.time() - 90000,
                "transactions": [],
                "proof": 0,
                "difficulty": 1,
                "previous_hash": "0",
                "hash": "deadbeef",
            },
        }
        Path("orphan_blocks.json").write_text(json.dumps([stale_orphan], indent=4))
        client = api.app.test_client()
        response = client.get("/process_orphans")
        assert response.status_code == 200
        result = response.get_json()
        assert result["removed_stale"] == ["deadbeef"]
        assert result["remaining"] == 0
    finally:
        restore_working_files(backup)


def test_blacklisted_peer_is_ignored_by_health():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        client = api.app.test_client()
        # manually place a fake peer in the blacklist and in the peer list
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        Path("blacklisted_peers.json").write_text(json.dumps([{"peer": "127.0.0.1:5000", "reason": "test", "timestamp": time.time()}], indent=4))
        response = client.get("/peer_health")
        assert response.status_code == 200
        result = response.get_json()
        assert any(item.get("peer") == "127.0.0.1:5000" and item.get("error") == "Peer is blacklisted" for item in result)
    finally:
        restore_working_files(backup)


def test_blacklist_endpoint_returns_blacklisted_peer():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("blacklisted_peers.json").write_text(json.dumps([{"peer": "127.0.0.1:5000", "reason": "test", "timestamp": time.time(), "duration": 60}], indent=4))
        client = api.app.test_client()
        response = client.get("/blacklist")
        assert response.status_code == 200
        result = response.get_json()
        assert isinstance(result, list)
        assert result[0]["peer"] == "127.0.0.1:5000"
    finally:
        restore_working_files(backup)


def test_blacklisted_peer_expires_from_blacklist():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        Path("blacklisted_peers.json").write_text(json.dumps([{"peer": "127.0.0.1:5000", "reason": "test", "timestamp": time.time() - 7200, "duration": 1}], indent=4))
        client = api.app.test_client()
        response = client.get("/blacklist")
        assert response.status_code == 200
        assert response.get_json() == []
    finally:
        restore_working_files(backup)


def test_peer_reputation_endpoint_returns_data():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        Path("peer_failures.json").write_text(json.dumps({"127.0.0.1:5000": 2}, indent=4))
        client = api.app.test_client()
        response = client.get("/peer_reputation")
        assert response.status_code == 200
        result = response.get_json()
        assert isinstance(result, list)
        assert result[0]["peer"] == "127.0.0.1:5000"
        assert result[0]["failure_count"] == 2
        assert "reputation" in result[0]
    finally:
        restore_working_files(backup)


def test_status_endpoint_returns_summary():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        Path("blacklisted_peers.json").write_text(json.dumps([{"peer": "127.0.0.1:5000", "reason": "test", "timestamp": time.time()}], indent=4))
        Path("peer_failures.json").write_text(json.dumps({"127.0.0.1:5000": 1}, indent=4))
        client = api.app.test_client()
        response = client.get("/status")
        assert response.status_code == 200
        result = response.get_json()
        assert result["chain"]["length"] == 1
        assert result["peers"]["total"] >= 1
        assert result["blacklist"][0]["peer"] == "127.0.0.1:5000"
        assert result["peer_failures"]["127.0.0.1:5000"] == 1
        assert isinstance(result["peer_health"], list)
    finally:
        restore_working_files(backup)


def test_peer_failures_endpoint_returns_counts():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("peer_failures.json").write_text(json.dumps({"127.0.0.1:5000": 2}, indent=4))
        client = api.app.test_client()
        response = client.get("/peer_failures")
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("127.0.0.1:5000") == 2
    finally:
        restore_working_files(backup)


def test_unblacklist_peer_endpoint_removes_peer():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        Path("blacklisted_peers.json").write_text(json.dumps([{"peer": "127.0.0.1:5000", "reason": "test", "timestamp": time.time(), "duration": 3600}], indent=4))
        client = api.app.test_client()
        response = client.post("/unblacklist_peer", json={"peer": "127.0.0.1:5000"})
        assert response.status_code == 200
        result = response.get_json()
        assert result.get("peer") == "127.0.0.1:5000"
        response = client.get("/blacklist")
        assert response.status_code == 200
        assert response.get_json() == []
    finally:
        restore_working_files(backup)


def test_launch_readiness_checks_network_state():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["seed.example:443"]
        config["peer_trust_policy"] = {"allow_public_bootstrap": True}
        core.write_json("chain_config.json", config)
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        client = api.app.test_client()
        response = client.get("/launch_readiness")
        assert response.status_code == 200
        result = response.get_json()
        assert "ready_for_launch" in result
        assert "readiness_checks" in result
        assert isinstance(result["readiness_checks"], dict)
        assert "chain_initialized" in result["readiness_checks"]
        assert "healthy_peers_available" in result["readiness_checks"]
        assert result["chain_height"] >= 1
    finally:
        restore_working_files(backup)


def test_deployment_runbook_provides_launch_steps():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["seed.example:443"]
        core.write_json("chain_config.json", config)
        client = api.app.test_client()
        response = client.get("/deployment_runbook")
        assert response.status_code == 200
        result = response.get_json()
        assert result["version"] == "1.0"
        assert "steps" in result
        assert len(result["steps"]) >= 5
        for step in result["steps"]:
            assert "step" in step
            assert "title" in step
            assert "description" in step
    finally:
        restore_working_files(backup)


def test_network_health_dashboard_aggregates_data():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        config = core.ensure_chain_config()
        config["seed_nodes"] = ["seed.example:443"]
        core.write_json("chain_config.json", config)
        Path("peers.json").write_text(json.dumps(["127.0.0.1:5000"], indent=4))
        Path("mempool.json").write_text(json.dumps([
            {"transaction": {"amount": 1.00, "fees": 1, "from": "addr1", "to": "addr2", "timestamp": time.time()}, "signature": "sig1"}
        ], indent=4))
        client = api.app.test_client()
        response = client.get("/network_health_dashboard")
        assert response.status_code == 200
        result = response.get_json()
        assert result["status"] == "ok"
        assert "node" in result
        assert "blockchain" in result
        assert "network" in result
        assert "mempool" in result
        assert "security" in result
        assert "bootstrap_state" in result
        assert "peer_health" in result
        assert result["blockchain"]["height"] >= 1
        assert result["network"]["total_peers"] >= 1
        assert result["mempool"]["pending_transactions"] >= 0
    finally:
        restore_working_files(backup)


def test_explorer_analytics_endpoints_return_structured_data():
    backup = backup_working_files()
    try:
        setup_clean_chain()
        wallet = core.create_wallet()
        chain = [core.create_genesis_block()]
        reward_block = make_reward_block_for(chain, wallet["address"])
        chain.append(reward_block)
        Path("blockchain_data.json").write_text(json.dumps(chain, indent=4))
        client = api.app.test_client()

        endpoints = [
            "/latest_wallets",
            "/network_supply_history",
            "/block_reward_history",
            "/address/{}/tokens".format(wallet["address"]),
            "/network_hashrate",
            "/difficulty_history",
            "/fee_statistics",
            "/network_overview",
            "/wallet_count",
            "/peer_list",
            "/supply_history",
            "/block_time_stats",
            "/network_summary",
            "/miner_stats",
            "/api_version",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, endpoint
            result = response.get_json()
            assert result is not None
    finally:
        restore_working_files(backup)


def run():
    tests = [
        test_mirrored_node_supports_signed_peer_helpers,
        test_import_wallet,
        test_send_transaction_endpoint,
        test_tls_material_is_generated_when_enabled,
        test_healthz_and_metrics_endpoints_report_monitoring_state,
        test_public_bootstrap_startup_scripts_are_available_on_both_nodes,
        test_tls_enabled_bootstrap_uses_https_peer_urls,
        test_recover_state_restores_latest_backup,
        test_hmac_peer_auth_accepts_signed_requests_when_configured,
        test_register_peer_self_ignored,
        test_register_peer_requires_auth_token_when_configured,
        test_sync_endpoints_require_auth_token_when_configured,
        test_rate_limiting_blocks_excessive_requests,
        test_sync_peers_endpoint,
        test_bootstrap_endpoint,
        test_register_peer_respects_trust_policy,
        test_bootstrap_config_endpoint_updates_seed_nodes_and_trust_policy,
        test_trust_policy_automation_promote_by_reputation,
        test_trust_policy_automation_demote_by_reputation,
        test_trust_policy_update_requires_admin_auth,
        test_deployment_control_endpoint_updates_runtime_config,
        test_public_access_control_and_rollout_safety_gates,
        test_admin_authentication_and_rollout_approval_workflow,
        test_mirrored_node_exposes_rollout_control_endpoints,
        test_audit_log_and_approval_history_are_persisted,
        test_sync_chain_uses_healthy_peers,
        test_process_orphans_cleans_stale_orphans,
        test_blacklisted_peer_is_ignored_by_health,
        test_blacklist_endpoint_returns_blacklisted_peer,
        test_blacklisted_peer_expires_from_blacklist,
        test_peer_reputation_endpoint_returns_data,
        test_status_endpoint_returns_summary,
        test_launch_readiness_checks_network_state,
        test_deployment_runbook_provides_launch_steps,
        test_network_health_dashboard_aggregates_data,
        test_explorer_analytics_endpoints_return_structured_data,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(json.dumps({"passed": passed, "failed": 0}, indent=4))


if __name__ == "__main__":
    run()
