<#
.SYNOPSIS
Shut the ATH Scanner Docker setup down.

.DESCRIPTION
Stops and removes every container of this project (neo4j, vllm and the optional laya
service included). Your data/, output/ and logs/ folders are bind mounts and are never
touched by this script. The Neo4j data lives in a named volume and survives a plain stop.

.PARAMETER Prune       Also remove the images built for this project.
.PARAMETER PurgeModels Also delete ALL named volumes: the downloaded models (Laya ~800 MB, Qwen3-4B ~8 GB, TimesFM checkpoint; re-downloaded on the next start) and the Neo4j graph.
.PARAMETER PurgeGraph  Delete only the Neo4j graph volume (it is rebuilt from data/documents.json on the next run). Use this if you deleted .env.neo4j and the database password no longer matches.
#>
param(
    [switch]$Prune,
    [switch]$PurgeModels,
    [switch]$PurgeGraph
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# docker writes ordinary progress to stderr; see the note in start.ps1.
function Invoke-Docker {
    param([string[]]$DockerArgs)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @DockerArgs | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

Write-Host "=== Stopping the ATH Scanner setup ===" -ForegroundColor Cyan

$down = @('compose', '--profile', 'laya', 'down', '--remove-orphans')
if ($Prune) { $down += @('--rmi', 'local') }
if ($PurgeModels) {
    $down += '--volumes'   # the named volumes are the model caches and the graph
    Write-Host "Removing the model and graph volumes." -ForegroundColor Yellow
}

$code = Invoke-Docker $down
if ($code -ne 0) {
    Write-Host "Error: docker compose down failed (exit $code)." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Still running for this project:" -ForegroundColor Cyan
$left = & docker compose --profile laya ps --format '{{.Name}}  {{.Status}}' 2>$null
if ($left) { $left | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  nothing" }
if ($PurgeGraph -and -not $PurgeModels) {
    $null = & docker volume rm kite-ath-scanner_neo4j_data 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "Neo4j graph volume removed." -ForegroundColor Yellow }
    else { Write-Host "Neo4j graph volume was not present." }
}
Write-Host ""
Write-Host "data/, output/ and logs/ are untouched." -ForegroundColor Green
