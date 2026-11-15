# KawaidCoin (KWD) High-Speed Miners (Multi-Core CPU & NVIDIA GPU)

Official high-performance miners for the KawaidCoin mainnet (`https://kawaidcoin.xyz`).
For basic single-core mining on lightweight laptops, download the standard miner directly from `https://kawaidcoin.xyz/explorer`.

## 1. Multi-Core CPU Miner (Windows / Linux / macOS)
Uses lock-free parallel multiprocessing across all selected CPU cores.
- **Requirements:** `pip install requests`
- **Windows Quick Start:** Double-click `start_multicore_miner.bat` and enter your KWD wallet address and core count.
- **CLI:** `python kwd_fast_miner.py <YOUR_KWD_WALLET> https://kawaidcoin.xyz 8`

## 2. NVIDIA CUDA GPU Miner (RTX / GTX GPUs)
Runs parallel SHA-256 batches directly on NVIDIA CUDA cores.
- **Requirements:** `pip install requests numpy cupy-cuda12x` (with NVIDIA drivers installed)
- **Windows Quick Start:** Double-click `start_gpu_miner.bat` and enter your KWD wallet address.
- **CLI:** `python kwd_gpu_remote_miner.py <YOUR_KWD_WALLET> https://kawaidcoin.xyz`
