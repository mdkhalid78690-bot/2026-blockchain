import json

from core import MEMPOOL_FILE, read_json, validate_transaction


mempool = read_json(MEMPOOL_FILE, [])

if not mempool:
    print("NO TRANSACTIONS IN MEMPOOL")
    raise SystemExit

valid, error = validate_transaction(mempool[0], read_json("blockchain_data.json", []), [])

print(json.dumps({
    "valid": valid,
    "error": error,
}, indent=4))
