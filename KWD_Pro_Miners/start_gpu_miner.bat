@echo off
title KawaidCoin (KWD) NVIDIA CUDA GPU Miner
cd /d "%~dp0"
set /p WALLET="Enter your KWD Wallet Address: "
python kwd_gpu_remote_miner.py %WALLET% https://kawaidcoin.xyz
pause
