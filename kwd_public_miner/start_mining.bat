@echo off
title KWD Community CPU Miner
echo =======================================================
echo           KAWAIDCOIN (KWD) COMMUNITY MINER
echo =======================================================

if not exist my_kwd_wallet.json (
    echo [*] No wallet found. Generating a new wallet first...
    python generate_wallet.py
    echo.
)

for /f "tokens=2 delims=:, " %%a in ('findstr "address" my_kwd_wallet.json') do set WALLET=%%~a
set WALLET=%WALLET:"=%

echo [*] Mining to Address: %WALLET%
echo [*] Connecting to Mainnet Seed Node: https://kawaidcoin.xyz
echo.

python kwd_remote_miner.py %WALLET% https://kawaidcoin.xyz
pause
