<#
.SYNOPSIS
Shut the ATH Scanner Docker setup down.

.DESCRIPTION
Stops and removes every container of this project (including the optional llm
and laya services, which live under compose profiles). Your data/, output/ and
logs/ folders are bind mounts and are never touched by this script.

.PARAMETER Prune       Also remove the images built for this project.
.PARAMETER PurgeModels Also delete the downloaded model volumes (Laya weights ~800 MB, Ollama model several GB; re-downloaded on the next start that uses them).
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

Write-Host "=== Stopping the ATH Scanner setup ===" -ForegroundColor Cyan

$down = @('compose', '--profile', 'laya', '--profile', 'llm', 'down', '--remove-orphans')
if ($Prune) { $down += @('--rmi', 'local') }
if ($PurgeModels) {
    $down += '--volumes'   # the only named volumes are the model caches
    Write-Host "Removing the model volumes." -ForegroundColor Yellow
}

$code = Invoke-Docker $down
if ($code -ne 0) {
    Write-Host "Error: docker compose down failed (exit $code)." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Still running for this project:" -ForegroundColor Cyan
$left = & docker compose --profile laya --profile llm ps --format '{{.Name}}  {{.Status}}' 2>$null
if ($left) { $left | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  nothing" }
Write-Host ""
Write-Host "data/, output/ and logs/ are untouched." -ForegroundColor Green
