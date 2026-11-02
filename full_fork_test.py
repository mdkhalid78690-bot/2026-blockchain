import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parent
BASE_DIR = ROOT.parent
NODE_DIRS = [
    ROOT,
    BASE_DIR / "2026 blockchain node2",
    BASE_DIR / "2026 blockchain node3",
    BASE_DIR / "2026 blockchain node4",
    BASE_DIR / "2026 blockchain node5",
]
PORTS = [5000, 5001, 5002, 5003, 5004]
FORK_BLOCK_PATH = ROOT / "fork_test_block5.json"


class NodeProcess:
    def __init__(self, port: int, cwd: Path, log_path: Path):
        self.port = port
        self.cwd = cwd
        self.log_path = log_path
        self.process: Optional[subprocess.Popen] = None

    def is_running(self) -> bool:
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2)
            return response.status_code < 500
        except Exception:
            return False

    def start(self) -> None:
        if self.is_running():
            print(f"[skip] Node on port {self.port} is already responding")
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            [sys.executable, "api.py"],
            cwd=str(self.cwd),
            stdout=self.log_path.open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        print(f"[start] Node on port {self.port} with PID {self.process.pid}")

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None


def wait_for_nodes(nodes: List[NodeProcess], timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready = [node for node in nodes if node.is_running()]
        if len(ready) == len(nodes):
            return
        time.sleep(2)
    missing = [node.port for node in nodes if not node.is_running()]
    raise RuntimeError(f"Nodes did not become ready: ports {missing}")


def patch_rate_limit(node_dir: Path) -> None:
    config_path = node_dir / "chain_config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data.setdefault("security", {})["rate_limit"] = 0
    data.setdefault("security", {})["rate_limit_window_seconds"] = 60
    data.setdefault("security", {})["rate_limit_ban_seconds"] = 60
    config_path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def reset_chain(port: int) -> None:
    response = requests.post(f"http://127.0.0.1:{port}/reset_chain", timeout=15)
    response.raise_for_status()
    print(f"[reset] Port {port}: {response.json()}")


def submit_competing_block(port: int, block: dict) -> dict:
    response = requests.post(f"http://127.0.0.1:{port}/receive_block", json=block, timeout=15)
    payload = response.json()
    print(f"[fork] Port {port}: {response.status_code} {payload}")
    return payload


def check_orphan_pool(port: int) -> List[dict]:
    response = requests.get(f"http://127.0.0.1:{port}/orphan_blocks", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected orphan response from port {port}: {payload}")
    return payload


def trigger_sync(port: int) -> dict:
    response = requests.get(f"http://127.0.0.1:{port}/sync_chain", timeout=20)
    response.raise_for_status()
    return response.json()


def main() -> int:
    if not FORK_BLOCK_PATH.exists():
        raise FileNotFoundError(f"Fork fixture not found: {FORK_BLOCK_PATH}")

    block = json.loads(FORK_BLOCK_PATH.read_text(encoding="utf-8"))
    nodes: List[NodeProcess] = []
    for idx, node_dir in enumerate(NODE_DIRS):
        port = PORTS[idx]
        log_path = ROOT / "logs" / f"node{idx + 1}.log"
        nodes.append(NodeProcess(port=port, cwd=node_dir, log_path=log_path))

    print("=== Starting five-node fork test ===")
    for node in nodes:
        node.start()

    try:
        wait_for_nodes(nodes, timeout=90)
        print("[ready] All five nodes are responding")

        for node in nodes:
            patch_rate_limit(node.cwd)
            reset_chain(node.port)

        print("[fork] Submitting competing block to all nodes")
        for node in nodes:
            payload = submit_competing_block(node.port, block)
            if payload.get("message") != "Block stored as orphan":
                raise RuntimeError(f"Unexpected fork result on port {node.port}: {payload}")

        print("[verify] Checking orphan pools")
        for node in nodes:
            orphans = check_orphan_pool(node.port)
            if not orphans:
                raise RuntimeError(f"No orphan blocks were stored on port {node.port}")
            print(f"[ok] Port {node.port} has {len(orphans)} orphan block(s)")

        print("[sync] Triggering chain sync on node 1")
        sync_result = trigger_sync(nodes[0].port)
        print(json.dumps(sync_result, indent=2))
        print("\n=== Fork test completed successfully ===")
        return 0
    finally:
        for node in nodes:
            if node.process is not None and node.process.poll() is None:
                node.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
