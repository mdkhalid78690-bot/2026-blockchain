@echo off
title KawaidCoin (KWD) Miner v0.1
echo ========================================================
echo         KAWAIDCOIN (KWD) OFFICIAL CPU MINER
echo ========================================================
echo.
set /p WALLET=Enter your KWD Wallet Address: 
if "%WALLET%"=="" (
    echo [ERROR] Wallet address cannot be empty!
    pause
    exit /b
)
echo.
set /p NODE_IP=Enter Node URL [Press Enter for default: http://127.0.0.1:5000]: 
if "%NODE_IP%"=="" set NODE_IP=http://127.0.0.1:5000
echo.
echo Connecting to %NODE_IP% and mining to %WALLET%...
python kwd_remote_miner.py %WALLET% %NODE_IP%
pause
