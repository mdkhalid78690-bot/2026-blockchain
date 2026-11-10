import json
import sys

import requests

from core import create_signed_transaction, get_balance, read_json, validate_transaction


def main():
    amount = float(sys.argv[1]) if len(sys.argv) > 1 else 25
    fee = float(sys.argv[2]) if len(sys.argv) > 2 else 1
    wallet1 = read_json("wallet1.json", {})
    wallet2 = read_json("wallet2.json", {})
    chain = read_json("blockchain_data.json", [])
    mempool = read_json("mempool.json", [])

    signed_tx = create_signed_transaction(
        wallet1["private_key"],
        wallet2["address"],
        amount,
        fee=fee,
        chain=chain,
        mempool=mempool,
    )

    valid, error = validate_transaction(signed_tx, chain, mempool)
    if not valid:
        print(json.dumps({"error": error, "balance": get_balance(wallet1["address"], chain)}, separators=(',', ':')))
        raise SystemExit(1)

    response = requests.post(
        "http://127.0.0.1:5000/create_transaction",
        json=signed_tx,
        timeout=5,
    )
    print(json.dumps(response.json(), separators=(',', ':')))


if __name__ == "__main__":
    main()
