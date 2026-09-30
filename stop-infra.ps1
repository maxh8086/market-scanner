<#
.SYNOPSIS
Stop the shared market-research infrastructure (Postgres, MongoDB, Neo4j, vLLM).

.DESCRIPTION
Runs the infra's own down.ps1. Other projects use these databases too, so this is a separate
script and stop.ps1 never calls it. Data and model weights are plain folders and stay put.

.PARAMETER Llm  Stop only the vLLM server (frees the GPU) and leave the databases running.
#>
param([switch]$Llm)

$ErrorActionPreference = 'Stop'
$InfraDir = if ($env:MARKET_INFRA_DIR) { $env:MARKET_INFRA_DIR } else { Join-Path (Split-Path $PSScriptRoot -Parent) 'Shared-Market-Research-Infra' }
$down = Join-Path $InfraDir 'down.ps1'
if (-not (Test-Path -LiteralPath $down)) {
    Write-Host "Error: $down not found. Set MARKET_INFRA_DIR or restore that folder." -ForegroundColor Red
    exit 1
}
Write-Host "=== Stopping the shared infrastructure ===" -ForegroundColor Cyan
Push-Location
try { if ($Llm) { & $down -Llm } else { & $down } } finally { Pop-Location }
exit $LASTEXITCODE
