<#
.SYNOPSIS
Start this project's Postgres container and wait until it is healthy.

.DESCRIPTION
Checks that Docker is reachable, runs `docker compose up -d scanner-postgres` from the repo root
(idempotent: a no-op when the container is already running), then polls the container's own
healthcheck every 2 seconds for up to 60 seconds until it reports 'healthy'.

Exit 0 when Postgres is healthy, 1 otherwise. On timeout the last status and the last 50 log
lines of the container are printed. Docker output is truncated to 50 lines.

start.ps1 calls this before anything uses Postgres. Tests are not meant to start containers.
This script never opens .env; docker compose reads it at runtime.

.EXAMPLE
powershell -NoProfile -File scripts\ensure_postgres.ps1
#>

$ErrorActionPreference = 'Stop'
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

$Container = 'market-scanner-postgres'
$TimeoutSeconds = 60
$PollSeconds = 2

# docker writes ordinary progress and errors to stderr; see the note in start.ps1.
# Output is printed truncated to 50 lines unless -Quiet is given. Returns the exit code.
function Invoke-Docker {
    param([string[]]$DockerArgs, [switch]$Quiet)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& docker @DockerArgs 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
        if (-not $Quiet) { $lines | Select-Object -First 50 | ForEach-Object { Write-Host $_ } }
        return $code
    } finally {
        $ErrorActionPreference = $previous
    }
}

# Current healthcheck status of the container, or 'missing' when it does not exist.
function Get-PostgresHealth {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& docker inspect -f '{{.State.Health.Status}}' $Container 2>$null)
        if ($LASTEXITCODE -ne 0) { return 'missing' }
        return ([string]($out | Select-Object -First 1)).Trim()
    } finally {
        $ErrorActionPreference = $previous
    }
}

# 1. Docker must answer.
$code = Invoke-Docker -DockerArgs @('info', '--format', '{{.ServerVersion}}') -Quiet
if ($code -ne 0) {
    Write-Host "Docker Desktop is not running (docker info failed). Start Docker Desktop and retry." -ForegroundColor Red
    exit 1
}

# 2. Start the service (no-op when it already runs).
$code = Invoke-Docker -DockerArgs @('compose', 'up', '-d', 'scanner-postgres')
if ($code -ne 0) {
    Write-Host "Could not start scanner-postgres (docker compose exit $code)." -ForegroundColor Red
    exit 1
}

# 3. Wait for the healthcheck.
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$status = ''
do {
    $status = Get-PostgresHealth
    if ($status -eq 'healthy') { break }
    Start-Sleep -Seconds $PollSeconds
} while ((Get-Date) -lt $deadline)

if ($status -ne 'healthy') {
    Write-Host "Postgres ($Container) is not healthy after $TimeoutSeconds seconds; last status: '$status'." -ForegroundColor Red
    Write-Host "Last 50 log lines of ${Container}:" -ForegroundColor Yellow
    Invoke-Docker -DockerArgs @('logs', '--tail', '50', $Container) | Out-Null
    exit 1
}

Write-Host "Postgres is healthy ($Container)." -ForegroundColor Green
exit 0
