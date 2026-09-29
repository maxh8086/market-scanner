#!/usr/bin/env pwsh
<#
.SYNOPSIS
Stop the ATH Scanner Docker containers.

.DESCRIPTION
Stops all running containers and optionally removes built images and
Hugging Face model weights.

.PARAMETER Prune
Remove built project images (docker compose down --rmi local).

.PARAMETER PurgeModels
Remove the Hugging Face weights volume (use with caution).

.EXAMPLE
./stop.ps1
./stop.ps1 -Prune
./stop.ps1 -Prune -PurgeModels
#>

param(
    [switch]$Prune,
    [switch]$PurgeModels
)

$ErrorActionPreference = 'Stop'

Write-Host "=== Stopping ATH Scanner Pipeline ===" -ForegroundColor Cyan

# Build down command
$downArgs = @("compose", "--profile", "laya", "down", "--remove-orphans")

if ($Prune) {
    $downArgs += "--rmi"
    $downArgs += "local"
    Write-Host "Removing built project images."
}

if ($PurgeModels) {
    $downArgs += "-v"
    Write-Host "WARNING: Removing Hugging Face weights volume. Models will be re-downloaded on next Laya start." -ForegroundColor Yellow
}

# Execute down
& docker @downArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to stop containers." -ForegroundColor Red
    exit 1
}

Write-Host "Containers and services stopped." -ForegroundColor Green

# Show what remains
Write-Host ""
Write-Host "=== Remaining Docker Resources ===" -ForegroundColor Cyan

$containers = & docker ps -q 2>&1
if ($containers) {
    Write-Host "Running containers:"
    & docker ps --format "table {{.Names}}`t{{.Image}}`t{{.Status}}" 2>&1
} else {
    Write-Host "No containers running."
}

$images = & docker images --filter "reference=ath-*" --filter "reference=*ath*" -q 2>&1
if ($images) {
    Write-Host ""
    Write-Host "Remaining ATH project images:"
    & docker images --filter "reference=ath-*" --filter "reference=*ath*" --format "table {{.Repository}}:{{.Tag}}`t{{.Size}}" 2>&1
}

$volumes = & docker volume ls --filter "name=ath" -q 2>&1
if ($volumes) {
    Write-Host ""
    Write-Host "Remaining ATH project volumes:"
    & docker volume ls --filter "name=ath" --format "table {{.Name}}`t{{.Driver}}" 2>&1
}

Write-Host ""
Write-Host "Stop completed." -ForegroundColor Green
