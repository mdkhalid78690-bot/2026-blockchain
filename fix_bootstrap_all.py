from pathlib import Path

root = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain')
paths = [
    root / 'api.py',
    root.parent / '2026 blockchain node2' / 'api.py',
    root.parent / '2026 blockchain node3' / 'api.py',
    root.parent / '2026 blockchain node4' / 'api.py',
    root.parent / '2026 blockchain node5' / 'api.py',
]
old = '''def bootstrap_on_startup(force=False):
    config = load_chain_config()
    seed_nodes = config.get("seed_nodes", []) or []
    if not seed_nodes:
        return {"message": "No seed nodes configured", "skipped": True}

    state = config.get("bootstrap_state", {}) or {}
    last_bootstrap = state.get("last_bootstrap_timestamp", 0)
    if not force and last_bootstrap and (time.time() - float(last_bootstrap)) < 300:
        return {"message": "Bootstrap already completed recently", "skipped": True, "peers": load_peers()}

    return bootstrap()
'''
new = '''def _invoke_sync_chain():
    sync_impl = globals().get("sync_chain")
    if callable(sync_impl):
        return sync_impl()
    return sync_chain()


def bootstrap_on_startup(force=False):
    config = load_chain_config()
    seed_nodes = config.get("seed_nodes", []) or []
    if not seed_nodes:
        return {"message": "No seed nodes configured", "skipped": True}

    state = config.get("bootstrap_state", {}) or {}
    last_bootstrap = state.get("last_bootstrap_timestamp", 0)
    if not force and last_bootstrap and (time.time() - float(last_bootstrap)) < 300:
        try:
            sync_result = _invoke_sync_chain()
        except Exception as exc:
            print(f"Post-bootstrap sync failed: {exc}")
            sync_result = {"error": str(exc)}
        return {
            "message": "Bootstrap already completed recently",
            "skipped": True,
            "peers": load_peers(),
            "sync": sync_result,
        }

    bootstrap_result = bootstrap()
    try:
        bootstrap_result["sync"] = _invoke_sync_chain()
    except Exception as exc:
        print(f"Post-bootstrap sync failed: {exc}")
        bootstrap_result["sync"] = {"error": str(exc)}
    return bootstrap_result
'''

for path in paths:
    if not path.exists():
        print(f'skipping {path}')
        continue
    text = path.read_text(encoding='utf-8')
    if old not in text:
        print(f'old block not found in {path}')
        continue
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    print(f'updated {path}')
