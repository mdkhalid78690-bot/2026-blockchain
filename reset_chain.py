import json

from core import reset_chain


chain, backup_path = reset_chain()

print(json.dumps({
    "message": "Chain reset to clean genesis block",
    "backup": backup_path,
    "blocks": len(chain),
}, indent=4))
