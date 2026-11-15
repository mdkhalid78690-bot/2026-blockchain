import sys, time, json, hashlib, requests
import cupy as cp
import numpy as np

DEFAULT_NODE = "https://kawaidcoin.xyz"

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

def fetch_work(node_url, address):
    try:
        r = requests.get(f"{node_url}/mining_job?address={address}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"\n[!] Node connection error ({node_url}): {e}")
    return None

def get_tip_height(node_url):
    try:
        r = requests.get(f"{node_url}/node_info", timeout=3)
        if r.status_code == 200:
            return int(r.json().get("height", -1))
    except Exception:
        pass
    return -1

def submit_block(node_url, block_data):
    try:
        r = requests.post(f"{node_url}/receive_block", json=block_data, timeout=15)
        return r.status_code in (200, 201), r.text
    except Exception as e:
        return False, str(e)

def mine_loop(address, node_url):
    device_name = cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
    print("=" * 64)
    print("       KAWAIDCOIN (KWD) CUDA GPU PARALLEL MINER")
    print("=" * 64)
    print(f"Payout Wallet Address : {address}")
    print(f"Connected Seed Node   : {node_url}")
    print(f"GPU Accelerator       : {device_name}")
    print("=" * 64)

    module = cp.RawModule(code=CUDA_KERNEL_SRC)
    kernel = module.get_function("search_proof_kernel")

    THREADS_PER_BLOCK = 256
    BLOCKS = 65536
    BATCH_SIZE = BLOCKS * THREADS_PER_BLOCK

    found_flag = cp.zeros(1, dtype=cp.int32)
    solution_proof = cp.zeros(1, dtype=cp.uint64)

    while True:
        work = fetch_work(node_url, address)
        if not work or "index" not in work:
            time.sleep(2)
            continue

        index = int(work["index"])
        diff = int(work["difficulty"])
        target_prefix = "0" * diff
        target_int = (1 << (256 - (diff * 4))) - 1
        target_h0 = np.uint32(target_int >> 224)

        template = dict(work)
        template.pop("hash", None)
        template["proof"] = "__PROOF_PLACEHOLDER__"
        canonical_template = json.dumps(template, sort_keys=True, separators=(",", ":"))
        prefix_str, suffix_str = canonical_template.split('"__PROOF_PLACEHOLDER__"', 1)
        prefix_bytes = prefix_str.encode()
        suffix_bytes = suffix_str.encode()

        d_prefix = cp.asarray(np.frombuffer(prefix_bytes, dtype=np.uint8))
        d_suffix = cp.asarray(np.frombuffer(suffix_bytes, dtype=np.uint8))

        print(f"\n[+] GPU Mining Block #{index} | Difficulty: {diff} | Batch: {BATCH_SIZE:,}")
        base_proof = np.uint64(0)
        t0 = time.time()
        last_tip_check = 0.0

        while True:
            found_flag.fill(0)
            kernel(
                (BLOCKS,), (THREADS_PER_BLOCK,),
                (d_prefix, np.int32(len(prefix_bytes)),
                 d_suffix, np.int32(len(suffix_bytes)),
                 base_proof, target_h0,
                 found_flag, solution_proof)
            )
            cp.cuda.Stream.null.synchronize()

            if int(found_flag[0]) == 1:
                solved_proof = int(solution_proof[0])
                h = hashlib.sha256(prefix_bytes + str(solved_proof).encode() + suffix_bytes).hexdigest()
                if h.startswith(target_prefix):
                    dt = max(time.time() - t0, 0.001)
                    print(f"\n[>>>] RTX 3050 SOLVED BLOCK #{index} in {dt:.2f}s! Proof: {solved_proof} -> Hash: {h[:28]}...")
                    work["proof"] = solved_proof
                    work["hash"] = h
                    ok, res = submit_block(node_url, work)
                    if ok:
                        print(f"[PASS] Block #{index} ACCEPTED ON-CHAIN! +50.0 KWD credited.")
                    else:
                        print(f"[!] Submission rejected: {res}")
                    break

            base_proof += np.uint64(BATCH_SIZE)
            now = time.time()
            dt = max(now - t0, 0.001)
            rate = int(int(base_proof) / dt)
            print(f"\r[*] Block #{index} | Tested: {int(base_proof):,} | RTX 3050 Speed: {rate:,} H/s   ", end="", flush=True)

            if now - last_tip_check >= 1.2:
                last_tip_check = now
                tip_h = get_tip_height(node_url)
                if tip_h >= index:
                    print(f"\n[~] Block #{index} solved by network (tip now #{tip_h}). Switching immediately...")
                    break

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python kwd_gpu_remote_miner.py <WALLET_ADDRESS> [NODE_URL]")
        sys.exit(1)

    miner_wallet = sys.argv[1].strip()
    target_node = sys.argv[2].strip() if len(sys.argv) >= 3 else DEFAULT_NODE
    mine_loop(miner_wallet, target_node)
