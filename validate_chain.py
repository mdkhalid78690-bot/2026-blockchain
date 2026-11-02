import json

from core import CHAIN_FILE, read_json, validate_chain


chain = read_json(CHAIN_FILE, [])
valid, error = validate_chain(chain)

print(json.dumps({
    "valid": valid,
    "blocks": len(chain),
    "error": error,
}, indent=4))
