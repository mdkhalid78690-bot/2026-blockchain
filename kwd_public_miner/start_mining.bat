@echo off
title KWD Remote Miner
echo =======================================================
echo          KAWAIDCOIN (KWD) COMMUNITY MINER
echo =======================================================

if not exist my_kwd_wallet.json (
    echo [*] No wallet found. Generating a new wallet first...
    python generate_wallet.py
    echo.
)

for /f "tokens=2 delims=:, " %%a in ('findstr "address" my_kwd_wallet.json') do set WALLET=%%~a
set WALLET=%WALLET:"=%

echo [*] Mining to Address: %WALLET%
echo [*] Connecting to KWD Seed Node...
echo.

python kwd_miner.py %WALLET% http://10.51.134.36:5000
pause
