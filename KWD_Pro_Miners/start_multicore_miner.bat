@echo off
title KawaidCoin (KWD) Multi-Core CPU Miner
cd /d "%~dp0"
set /p WALLET="Enter your KWD Wallet Address: "
set /p CORES="Enter CPU worker cores to use (e.g. 4, 8, 11): "
python kwd_fast_miner.py %WALLET% https://kawaidcoin.xyz %CORES%
pause
