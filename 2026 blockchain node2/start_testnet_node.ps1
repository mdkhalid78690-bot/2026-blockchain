param(
    [int]$Port = 5001,
    [string]$Host = "0.0.0.0",
    [string]$NodeId = "kwd-node-public-2",
    [string[]]$SeedNodes = @()
)

$nodeConfig = @{
    node_id = $NodeId
    port = $Port
    host = $Host
}

$nodeConfig | ConvertTo-Json -Depth 3 | Set-Content -Path "node_config.json"
Write-Host "Wrote node_config.json with host=$Host port=$Port node_id=$NodeId"

if ($SeedNodes.Count -gt 0) {
    $config = Get-Content -Path "chain_config.json" -Raw | ConvertFrom-Json
    $config.seed_nodes = $SeedNodes
    $config | ConvertTo-Json -Depth 6 | Set-Content -Path "chain_config.json"
    Write-Host "Updated chain_config.json with seed nodes: $($SeedNodes -join ', ')"
}

Write-Host "Starting API node on $Host:$Port..."
python api.py
