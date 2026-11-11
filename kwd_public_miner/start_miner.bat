@echo off
title KawaidCoin (KWD) Official CPU Miner
echo ========================================================
echo          KAWAIDCOIN (KWD) OFFICIAL CPU MINER
echo ========================================================
echo.
set /p WALLET=Enter your KWD Wallet Address:
if "%WALLET%"=="" (
    echo [ERROR] Wallet address cannot be empty!
    pause
    exit /b
)
echo.
set /p NODE_IP=Enter Seed Node URL [Press Enter for https://kawaidcoin.xyz]:
if "%NODE_IP%"=="" set NODE_IP=https://kawaidcoin.xyz
echo.
echo Connecting to %NODE_IP% and mining to %WALLET%...
python kwd_remote_miner.py %WALLET% %NODE_IP%
pause
