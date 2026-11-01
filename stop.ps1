<#
.SYNOPSIS
Shut the Market Scanner Docker setup down.

.DESCRIPTION
Stops and removes every container of this project (including the optional laya service, the UI
and the collector, which run until you stop them).
Your data/, output/ and logs/ folders are bind mounts and are never touched by this script.
The shared databases and vLLM server belong to the separate Shared-Market-Research-Infra
project and other projects may be using them, so afterwards you are asked whether to stop them
too. Yes runs stop-infra.ps1; no leaves them running.

.PARAMETER StopInfra   Stop the shared infrastructure as well, without asking.
.PARAMETER KeepInfra   Leave the shared infrastructure running, without asking (use this in scripts).
.PARAMETER Prune       Also remove the images built for this project.
.PARAMETER PurgeModels Also delete this project's named volumes (the Laya model cache, ~800 MB, re-downloaded on the next -WithLaya start). The Qwen3-4B and TimesFM weights are in the shared infra's models folder and are not touched.
#>
param(
    [switch]$StopInfra,
    [switch]$KeepInfra,
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

# The shared infrastructure is a separate project; ask before touching it.
if ($StopInfra -and $KeepInfra) {
    Write-Host "Error: -StopInfra and -KeepInfra contradict each other." -ForegroundColor Red
    exit 1
}
$stopShared = $StopInfra.IsPresent
if (-not $StopInfra -and -not $KeepInfra) {
    Write-Host ""
    try {
        $answer = Read-Host "Stop the shared infrastructure too (Postgres, MongoDB, Neo4j, vLLM)? Other projects may be using it. [y/N]"
        $stopShared = $answer -match '^\s*y(es)?\s*$'
    } catch {
        Write-Host "No console to ask on -- leaving the shared infrastructure running." -ForegroundColor Yellow
    }
}
Write-Host ""
if ($stopShared) {
    & (Join-Path $PSScriptRoot 'stop-infra.ps1')
    exit $LASTEXITCODE
}
Write-Host "Shared infrastructure left running. ./stop-infra.ps1 stops it." -ForegroundColor Green
