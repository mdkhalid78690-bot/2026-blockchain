python miner.py
git add blockchain_data.json
git commit -m "Sync latest CPU-mined block from laptop"
git pull --rebase origin main
git push origin main
Write-Host "`nMined on laptop CPU and permanently saved to Cloud & GitHub!" -ForegroundColor Green
