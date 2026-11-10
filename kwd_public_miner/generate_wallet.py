import os, hashlib, json, time

def generate_keypair():
    # Cryptographically strong key generation
    seed = os.urandom(32) + str(time.time_ns()).encode()
    priv = hashlib.sha256(seed).hexdigest()
    pub = hashlib.sha256(priv.encode()).hexdigest()
    addr = pub # In KWD, public key hash serves as public payout address
    return priv, pub, addr

if __name__ == "__main__":
    print("=" * 55)
    print("      KAWAIDCOIN (KWD) ? NEW WALLET GENERATOR")
    print("=" * 55)
    
    priv, pub, addr = generate_keypair()
    wallet_data = {
        "address": addr,
        "public_key": pub,
        "private_key": priv
    }
    
    with open("my_kwd_wallet.json", "w") as f:
        json.dump(wallet_data, f, indent=4)
        
    print("[PASS] Wallet Generated Successfully!")
    print(f"Address     : {addr}")
    print(f"Private Key : {priv[:8]}...{priv[-8:]} (Saved to my_kwd_wallet.json)")
    print("\nKeep my_kwd_wallet.json private! You can share your address to receive KWD.")
    print("=" * 55)
