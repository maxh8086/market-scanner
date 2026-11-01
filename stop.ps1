<#
.SYNOPSIS
Shut the Market Scanner Docker setup down.

.DESCRIPTION
Stops and removes every container of this project (including the optional laya service, the UI
and the collector, which run until you stop them, and this project's Postgres, MongoDB and Neo4j).
Your data/, output/ and logs/ folders are bind mounts and are never touched by this script.

.PARAMETER Prune       Also remove the images built for this project.
.PARAMETER PurgeModels Also delete this project's named volumes (the Laya model cache, ~800 MB, re-downloaded on the next -WithLaya start). The TimesFM weights are in data\huggingface and are not touched.
#>
param(
    [switch]$Prune,
    [switch]$PurgeModels
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

Write-Host "=== Stopping the Market Scanner setup ===" -ForegroundColor Cyan

$down = @('compose', '--profile', 'laya', 'down', '--remove-orphans')
if ($Prune) { $down += @('--rmi', 'local') }
if ($PurgeModels) {
    $down += '--volumes'   # the only named volume left is the Laya model cache
    Write-Host "Removing the Laya model cache volume." -ForegroundColor Yellow
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
Write-Host ""
Write-Host "data/, output/ and logs/ are untouched." -ForegroundColor Green
