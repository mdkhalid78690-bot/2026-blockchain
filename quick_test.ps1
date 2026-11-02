# Quick Test Script for Windows PowerShell
# Run to verify all nodes are working
# Usage: .\quick_test.ps1

function Test-Endpoint {
    param(
        [string]$Url,
        [string]$Name
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -ErrorAction Stop -TimeoutSec 5
        Write-Host "✅ PASS | $Name" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "❌ FAIL | $Name" -ForegroundColor Red
        return $false
    }
}

function Test-Node {
    param(
        [int]$Port
    )
    
    Write-Host "`n$('='*60)" -ForegroundColor Cyan
    Write-Host "  Testing Node on Port $Port" -ForegroundColor Cyan
    Write-Host "$('='*60)`n" -ForegroundColor Cyan
    
    $baseUrl = "http://127.0.0.1:$Port"
    $results = @()
    
    $results += Test-Endpoint "$baseUrl/status" "Basic Status Endpoint"
    $results += Test-Endpoint "$baseUrl/healthz" "Health Check Endpoint"
    $results += Test-Endpoint "$baseUrl/peer_health" "Peer Health Endpoint"
    $results += Test-Endpoint "$baseUrl/deployment_status" "Deployment Status Endpoint"
    $results += Test-Endpoint "$baseUrl/launch_readiness" "Launch Readiness Endpoint"
    $results += Test-Endpoint "$baseUrl/deployment_runbook" "Deployment Runbook Endpoint"
    $results += Test-Endpoint "$baseUrl/network_health_dashboard" "Network Health Dashboard"
    $results += Test-Endpoint "$baseUrl/ops_status" "Operations Status Endpoint"
    $results += Test-Endpoint "$baseUrl/blockchain" "Blockchain Endpoint"
    $results += Test-Endpoint "$baseUrl/validate_chain" "Validate Chain Endpoint"
    
    return $results -contains $false ? $false : $true
}

Write-Host "`n$('='*60)" -ForegroundColor Cyan
Write-Host "  🧪 KawaidCoin Testnet - Quick Test Suite" -ForegroundColor Cyan
Write-Host "$('='*60)" -ForegroundColor Cyan

$node1Pass = Test-Node 5000
$node2Pass = Test-Node 5001

Write-Host "`n$('='*60)" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "$('='*60)`n" -ForegroundColor Cyan

if ($node1Pass) {
    Write-Host "✅ PASS | Main Node (5000)" -ForegroundColor Green
} else {
    Write-Host "❌ FAIL | Main Node (5000)" -ForegroundColor Red
}

if ($node2Pass) {
    Write-Host "✅ PASS | Node 2 (5001)" -ForegroundColor Green
} else {
    Write-Host "❌ FAIL | Node 2 (5001)" -ForegroundColor Red
}

if ($node1Pass -and $node2Pass) {
    Write-Host "`n$('='*60)" -ForegroundColor Green
    Write-Host "  ✅ ALL TESTS PASSED - Nodes are ready!" -ForegroundColor Green
    Write-Host "$('='*60)`n" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n$('='*60)" -ForegroundColor Red
    Write-Host "  ❌ SOME TESTS FAILED - Check connectivity" -ForegroundColor Red
    Write-Host "$('='*60)`n" -ForegroundColor Red
    exit 1
}
