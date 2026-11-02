Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "All 5 KWD Blockchain nodes stopped!" -ForegroundColor Yellow
