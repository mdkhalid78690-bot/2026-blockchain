from ecdsa import SigningKey, SECP256k1
import hashlib
import json

private_key = SigningKey.generate(curve=SECP256k1)
public_key = private_key.verifying_key

wallet = {
    "private_key": private_key.to_string().hex(),
    "public_key": public_key.to_string().hex(),
    "address": hashlib.sha256(
        public_key.to_string().hex().encode()
    ).hexdigest()
}

with open("wallet2.json", "w") as f:
    json.dump(wallet, f, indent=4)

print("Wallet saved!")
print("Address:", wallet["address"])