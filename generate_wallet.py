import hashlib, json
from ecdsa import SigningKey, SECP256k1

def generate_keypair():
    sk = SigningKey.generate(curve=SECP256k1)
    priv_hex = sk.to_string().hex()
    vk = sk.verifying_key
    pub_hex = vk.to_string().hex()
    # Matches core.py line 1131
    address = hashlib.sha256(pub_hex.encode()).hexdigest()
    return priv_hex, pub_hex, address

if __name__ == "__main__":
    print("=" * 60)
    print("      KAWAIDCOIN (KWD) OFFICIAL ECDSA WALLET GENERATOR")
    print("=" * 60)
    priv, pub, addr = generate_keypair()
    wallet_data = {
        "address": addr,
        "public_key": pub,
        "private_key": priv
    }
    with open("my_kwd_wallet.json", "w", encoding="utf-8") as f:
        json.dump(wallet_data, f, indent=4)

    print("[PASS] SECP256k1 Keypair Generated Successfully!")
    print(f"Address     : {addr}")
    print(f"Public Key  : {pub[:16]}...{pub[-16:]}")
    print(f"Private Key : {priv[:8]}...{priv[-8:]} (Saved to my_kwd_wallet.json)")
    print("\nKeep my_kwd_wallet.json secure! Share only your Address to receive KWD.")
    print("=" * 60)
