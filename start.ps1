#!/usr/bin/env pwsh
<#
.SYNOPSIS
Manually start the ATH Scanner pipeline in Docker.

.DESCRIPTION
Runs the scanner, enrichment, crosscheck, and optionally portfolio and Laya
stages in order, with bind-mounted data directories on the host.

.PARAMETER Symbols
Symbols to scan (passed to ath_scan.py --symbols).

.PARAMETER WithLaya
Start the Laya decision model as a long-running service (profile laya).

.PARAMETER SkipEnrich
Skip the enrichment stage.

.PARAMETER SkipCrosscheck
Skip the crosscheck stage.

.PARAMETER SkipPortfolio
Skip the portfolio stage.

.PARAMETER Rebuild
Force a full docker compose build before running.

.EXAMPLE
./start.ps1
./start.ps1 -Symbols "INFY,TCS"
./start.ps1 -WithLaya -Rebuild
#>

param(
    [string]$Symbols,
    [switch]$WithLaya,
    [switch]$SkipEnrich,
    [switch]$SkipCrosscheck,
    [switch]$SkipPortfolio,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'

function Write-Stage {
    param([string]$Message)
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Write-Error-Message {
    param([string]$Message)
    Write-Host "Error: $Message" -ForegroundColor Red
}

$startTime = Get-Date

# Verify Docker daemon
Write-Stage "Checking Docker daemon"
try {
    $dockerInfo = & docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Message "Docker daemon not responding. Ensure Docker Desktop is running."
        exit 1
    }
    Write-Host "Docker daemon is running."
} catch {
    Write-Error-Message "Docker command not found. Ensure Docker is installed."
    exit 1
}

# Verify .env exists
Write-Stage "Verifying .env"
if (-not (Test-Path ".env")) {
    Write-Error-Message ".env file not found. Copy .env.example to .env and fill in your credentials."
    exit 1
}
Write-Host ".env file found."

# Build
Write-Stage "Building Docker images"
$buildStart = Get-Date
if ($Rebuild) {
    & docker compose build --no-cache 2>&1
} else {
    & docker compose build 2>&1
}
if ($LASTEXITCODE -ne 0) {
    Write-Error-Message "Docker build failed."
    exit 1
}
$buildEnd = Get-Date
$buildDuration = [int](($buildEnd - $buildStart).TotalSeconds)
Write-Host "Build completed in $buildDuration seconds."

# Start Laya if requested
if ($WithLaya) {
    Write-Stage "Starting Laya service"
    $layaStart = Get-Date
    & docker compose --profile laya up -d laya 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Message "Failed to start Laya."
        exit 1
    }

    # Wait for healthcheck
    Write-Host "Waiting for Laya healthcheck..."
    $maxRetries = 60
    $retries = 0
    while ($retries -lt $maxRetries) {
        $health = & docker compose exec laya curl -s http://localhost:8000/health 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Laya is healthy."
            break
        }
        $retries++
        Start-Sleep -Seconds 1
    }
    if ($retries -eq $maxRetries) {
        Write-Error-Message "Laya healthcheck timed out."
        exit 1
    }
    $layaEnd = Get-Date
    $layaDuration = [int](($layaEnd - $layaStart).TotalSeconds)
    Write-Host "Laya ready in $layaDuration seconds."
}

# Run scanner
Write-Stage "Running ATH Scanner"
$scanStart = Get-Date
$scanArgs = @("compose", "run", "--rm", "scanner")
if ($Symbols) {
    $scanArgs += @("--symbols", $Symbols)
}
& docker @scanArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error-Message "Scanner failed."
    exit 1
}
$scanEnd = Get-Date
$scanDuration = [int](($scanEnd - $scanStart).TotalSeconds)
Write-Host "Scanner completed in $scanDuration seconds."

# Run enrich
if (-not $SkipEnrich) {
    Write-Stage "Running Enrichment"
    $enrichStart = Get-Date
    & docker compose run --rm enrich --all 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Message "Enrichment failed."
        exit 1
    }
    $enrichEnd = Get-Date
    $enrichDuration = [int](($enrichEnd - $enrichStart).TotalSeconds)
    Write-Host "Enrichment completed in $enrichDuration seconds."
} else {
    Write-Host "Enrichment skipped."
}

# Run crosscheck
if (-not $SkipCrosscheck) {
    Write-Stage "Running Crosscheck"
    $crossStart = Get-Date
    & docker compose run --rm crosscheck --scan output 2>&1
    $crossExit = $LASTEXITCODE
    $crossEnd = Get-Date
    $crossDuration = [int](($crossEnd - $crossStart).TotalSeconds)

    if ($crossExit -eq 0) {
        Write-Host "Crosscheck completed in $crossDuration seconds."
    } elseif ($crossExit -eq 1) {
        Write-Host "Crosscheck: divergence detected (exit code 1). This is a warning, not a failure." -ForegroundColor Yellow
    } else {
        Write-Error-Message "Crosscheck failed with exit code $crossExit"
        exit 1
    }
} else {
    Write-Host "Crosscheck skipped."
}

# Run portfolio
if (-not $SkipPortfolio) {
    Write-Stage "Running Portfolio Overlay"
    $portStart = Get-Date
    & docker compose run --rm portfolio --output-dir output 2>&1
    $portExit = $LASTEXITCODE
    $portEnd = Get-Date
    $portDuration = [int](($portEnd - $portStart).TotalSeconds)

    if ($portExit -eq 0) {
        Write-Host "Portfolio completed in $portDuration seconds."
    } elseif ($portExit -eq 2) {
        Write-Host "Portfolio: no holdings source available (exit code 2). This is a warning, not a failure." -ForegroundColor Yellow
    } else {
        Write-Error-Message "Portfolio failed with exit code $portExit"
        exit 1
    }
} else {
    Write-Host "Portfolio skipped."
}

# Summary
Write-Stage "Pipeline Summary"
$totalEnd = Get-Date
$totalDuration = [int](($totalEnd - $startTime).TotalSeconds)

Write-Host "Total elapsed time: $totalDuration seconds"
Write-Host ""
Write-Host "Output files:"
if (Test-Path "output") {
    Get-ChildItem -Path "output" -File | ForEach-Object {
        Write-Host "  output/$($_.Name)"
    }
}
Write-Host ""
Write-Host "Data files:"
if (Test-Path "data") {
    Get-ChildItem -Path "data" -File | ForEach-Object {
        Write-Host "  data/$($_.Name)"
    }
}
Write-Host ""
Write-Host "Pipeline completed successfully." -ForegroundColor Green
