import sys
import time
import json
import hashlib
import requests
import cupy as cp
import numpy as np
import core

NODE_URL = "http://127.0.0.1:5000"

def canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))

def calculate_hash(block):
    block_copy = dict(block)
    block_copy.pop("hash", None)
    return hashlib.sha256(canonical_json(block_copy).encode()).hexdigest()

def get_work(node_url=NODE_URL):
    try:
        chain = core.read_json(core.CHAIN_FILE, [])
        if not chain:
            return None
        tip = chain[-1]
        next_index = int(tip.get("index", len(chain))) + 1
        prev_hash = tip.get("hash", "")
        difficulty = int(core.calculate_next_difficulty(chain))
        target = (1 << (256 - (difficulty * 4))) - 1

        reward = 12.5
        try:
            r = requests.get(f"{node_url}/halving_info", timeout=2)
            if r.status_code == 200:
                reward = float(r.json().get("current_reward", 12.5))
        except Exception:
            pass

        return {
            "height": next_index,
            "previous_hash": prev_hash,
            "difficulty": difficulty,
            "target": target,
            "reward": reward
        }
    except Exception as e:
        print(f"[!] get_work error: {e}")
        return None

def build_reward_tx(wallet_address, reward_amount, next_index, timestamp):
    tx_inner = {
        "from": "NETWORK",
        "to": wallet_address,
        "amount": float(reward_amount),
        "fee": 0.0,
        "timestamp": timestamp,
        "nonce": next_index
    }
    tx_inner["txid"] = core.hash_data(core.tx_signing_payload(tx_inner))
    return {
        "signature": core.MINING_REWARD_SIGNATURE,
        "transaction": tx_inner
    }

def commit_block(candidate_block, node_url):
    try:
        res = requests.post(f"{node_url}/receive_block", json=candidate_block, timeout=5)
        print(f"[>] Node HTTP Response: {res.status_code} - {res.text}")
        if res.status_code in (200, 201):
            return
    except Exception:
        print("[*] HTTP Node unavailable. Executing Bitcoin v0.1 autonomous disk commit...")

    chain = core.read_json(core.CHAIN_FILE, [])
    tip = chain[-1] if chain else None
    ok, err = core.validate_block(
        candidate_block,
        previous_block=tip,
        full_transactions=True,
        prior_chain=chain,
        check_future_time=False
    )
    if ok:
        chain.append(candidate_block)
        core.write_json(core.CHAIN_FILE, chain)
        print(f"[+] SUCCESS: Block #{candidate_block['index']} committed directly to ledger!")
    else:
        print(f"[!] Local validation rejected: {err}")

CUDA_KERNEL_SRC = r"""
extern "C" {
__device__ __constant__ unsigned int K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

#define ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z) (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define SIGMA0(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define SIGMA1(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIGMA_S0(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ ((x) >> 3))
#define SIGMA_S1(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ ((x) >> 10))

__device__ __forceinline__ unsigned char get_byte(
    int idx,
    const unsigned char* __restrict__ prefix, int prefix_len,
    const char* num_str, int num_len,
    const unsigned char* __restrict__ suffix, int suffix_len,
    int total_len, int padded_len
) {
    if (idx < prefix_len) return prefix[idx];
    int p_num = prefix_len + num_len;
    if (idx < p_num) return (unsigned char)num_str[idx - prefix_len];
    if (idx < total_len) return suffix[idx - p_num];
    if (idx == total_len) return 0x80;
    if (idx >= padded_len - 8) {
        int shift = (padded_len - 1 - idx) * 8;
        return (unsigned char)(((unsigned long long)total_len * 8ULL) >> shift);
    }
    return 0x00;
}

extern "C" __global__ __launch_bounds__(256) void search_proof_kernel(
    const unsigned char* __restrict__ prefix, int prefix_len,
    const unsigned char* __restrict__ suffix, int suffix_len,
    unsigned long long base_proof,
    unsigned int target_h0,
    int* __restrict__ found_flag,
    unsigned long long* __restrict__ solution_proof
) {
    if (*found_flag) return;
    unsigned long long tid = (unsigned long long)blockDim.x * blockIdx.x + threadIdx.x;
    unsigned long long proof = base_proof + tid;

    char num_str[20];
    int num_len = 0;
    unsigned long long temp = proof;
    if (temp == 0) {
        num_str[num_len++] = '0';
    } else {
        while (temp > 0) {
            num_str[num_len++] = '0' + (int)(temp % 10);
            temp /= 10;
        }
        for (int i = 0; i < num_len / 2; ++i) {
            char tc = num_str[i];
            num_str[i] = num_str[num_len - 1 - i];
            num_str[num_len - 1 - i] = tc;
        }
    }

    int total_len = prefix_len + num_len + suffix_len;
    int blocks = (total_len + 9 + 63) / 64;
    int padded_len = blocks * 64;

    unsigned int state[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };

    for (int b = 0; b < blocks; ++b) {
        unsigned int w[16];
        int base_idx = b * 64;
        for (int i = 0; i < 16; ++i) {
            int j = base_idx + i * 4;
            unsigned int b0 = get_byte(j,     prefix, prefix_len, num_str, num_len, suffix, suffix_len, total_len, padded_len);
            unsigned int b1 = get_byte(j + 1, prefix, prefix_len, num_str, num_len, suffix, suffix_len, total_len, padded_len);
            unsigned int b2 = get_byte(j + 2, prefix, prefix_len, num_str, num_len, suffix, suffix_len, total_len, padded_len);
            unsigned int b3 = get_byte(j + 3, prefix, prefix_len, num_str, num_len, suffix, suffix_len, total_len, padded_len);
            w[i] = (b0 << 24) | (b1 << 16) | (b2 << 8) | b3;
        }

        unsigned int a = state[0], b_reg = state[1], c = state[2], d = state[3];
        unsigned int e = state[4], f = state[5], g = state[6], h = state[7];

        for (int i = 0; i < 64; ++i) {
            unsigned int wi;
            if (i < 16) {
                wi = w[i];
            } else {
                wi = SIGMA_S1(w[(i - 2) & 15]) + w[(i - 7) & 15] + SIGMA_S0(w[(i - 15) & 15]) + w[i & 15];
                w[i & 15] = wi;
            }
            unsigned int t1 = h + SIGMA1(e) + CH(e, f, g) + K[i] + wi;
            unsigned int t2 = SIGMA0(a) + MAJ(a, b_reg, c);
            h = g; g = f; f = e; e = d + t1;
            d = c; c = b_reg; b_reg = a; a = t1 + t2;
        }

        state[0] += a; state[1] += b_reg; state[2] += c; state[3] += d;
        state[4] += e; state[5] += f;     state[6] += g; state[7] += h;
    }

    if (state[0] <= target_h0) {
        if (atomicCAS(found_flag, 0, 1) == 0) {
            *solution_proof = proof;
        }
    }
}
}
"""

def mine_loop(wallet_address, node_url=NODE_URL):
    device_name = cp.cuda.runtime.getDeviceProperties(0)['name'].decode()
    print("=" * 64)
    print("  KWD Bitcoin v0.3 GPU Miner (CUDA Accelerated)")
    print(f"  Target Wallet: {wallet_address}")
    print(f"  GPU Engine   : {device_name}")
    print(f"  Master Node  : {node_url}")
    print("=" * 64)

    module = cp.RawModule(code=CUDA_KERNEL_SRC)
    kernel = module.get_function("search_proof_kernel")

    THREADS_PER_BLOCK = 256
    BLOCKS = 65536
    BATCH_SIZE = BLOCKS * THREADS_PER_BLOCK  # 16,777,216 hashes per GPU launch

    found_flag = cp.zeros(1, dtype=cp.int32)
    solution_proof = cp.zeros(1, dtype=cp.uint64)

    while True:
        work = get_work(node_url)
        if not work or not work["previous_hash"]:
            print("[!] Unable to fetch work. Retrying in 4s...")
            time.sleep(4)
            continue

        idx = work["height"]
        target_diff = work["difficulty"]
        target = work["target"]
        prev_hash = work["previous_hash"]
        reward_amt = work["reward"]

        print(f"\n[*] Mining Block #{idx} | Difficulty: {target_diff} on {device_name}")
        print(f"[*] Target: 0x{target:064x}"[:60] + "...")
        print(f"[*] Previous Hash: {prev_hash[:32]}...")

        block_ts = max(time.time(), float(core.read_json(core.CHAIN_FILE, [{}])[-1].get("timestamp", 0)) + 0.001)
        reward_tx = build_reward_tx(wallet_address, reward_amt, idx, block_ts)

        template_block = {
            "index": idx,
            "timestamp": block_ts,
            "proof": "__PROOF_PLACEHOLDER__",
            "previous_hash": prev_hash,
            "difficulty": target_diff,
            "transactions": [reward_tx]
        }
        raw_template = canonical_json(template_block)
        prefix_str, suffix_str = raw_template.split('"__PROOF_PLACEHOLDER__"')

        d_prefix = cp.asarray(np.frombuffer(prefix_str.encode(), dtype=np.uint8))
        d_suffix = cp.asarray(np.frombuffer(suffix_str.encode(), dtype=np.uint8))
        target_h0 = np.uint32(target >> 224)

        base_proof = np.uint64(0)
        start_time = time.time()
        found = False

        while not found:
            found_flag.fill(0)
            kernel(
                (BLOCKS,), (THREADS_PER_BLOCK,),
                (d_prefix, np.int32(len(prefix_str)),
                 d_suffix, np.int32(len(suffix_str)),
                 base_proof, target_h0,
                 found_flag, solution_proof)
            )
            cp.cuda.Stream.null.synchronize()

            if int(found_flag[0]) == 1:
                solved_proof = int(solution_proof[0])
                candidate_block = {
                    "index": idx,
                    "timestamp": block_ts,
                    "proof": solved_proof,
                    "previous_hash": prev_hash,
                    "difficulty": target_diff,
                    "transactions": [reward_tx]
                }
                h = calculate_hash(candidate_block)
                if int(h, 16) < target:
                    elapsed = round(time.time() - start_time, 2)
                    print(f"\n[+] SOLVED BY RTX GPU! Proof: {solved_proof} in {elapsed}s | Hash: {h[:24]}...")
                    candidate_block["hash"] = h
                    commit_block(candidate_block, node_url)
                    found = True
                    break

            base_proof += np.uint64(BATCH_SIZE)
            elapsed = max(0.001, time.time() - start_time)
            hrate = int(int(base_proof) / elapsed)
            sys.stdout.write(f"\r[*] RTX 3050 Parallel Hashrate: {hrate:,} H/s | Tested: {int(base_proof):,}")
            sys.stdout.flush()

        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_gpu_miner.py <YOUR_WALLET_ADDRESS>")
        sys.exit(1)
    mine_loop(sys.argv[1])
