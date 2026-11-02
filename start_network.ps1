$nodes = @(
    "C:\Users\MD khalid\Desktop\2026 blockchain",
    "C:\Users\MD khalid\Desktop\2026 blockchain node2",
    "C:\Users\MD khalid\Desktop\2026 blockchain node3",
    "C:\Users\MD khalid\Desktop\2026 blockchain node4",
    "C:\Users\MD khalid\Desktop\2026 blockchain node5"
)
foreach ($d in $nodes) {
    if (Test-Path $d) {
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$d'; python api.py"
    }
}
Start-Sleep -Seconds 5
Start-Process "http://127.0.0.1:5000/explorer"
Write-Host "All 5 KWD nodes started and Explorer opened!" -ForegroundColor Green
