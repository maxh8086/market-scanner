<#
.SYNOPSIS
Stop Market Scanner. Add -Infra to also stop the shared infra (databases, vLLM). Data is never deleted.
#>
param([switch]$Infra)
$ErrorActionPreference = 'Continue'  # native tools write progress to stderr; exit codes are checked explicitly
Set-Location -Path $PSScriptRoot
$InfraDir = if ($env:MARKET_INFRA_DIR) { $env:MARKET_INFRA_DIR } else { Join-Path $PSScriptRoot 'infra' }
$env:MARKET_INFRA_DIR = $InfraDir
if (Test-Path (Join-Path $PSScriptRoot 'app\docker-compose.yml')) {
    & docker compose --profile laya down --remove-orphans
}
if ($Infra -and (Test-Path (Join-Path $InfraDir 'down.ps1'))) { & (Join-Path $InfraDir 'down.ps1') -Llm; & (Join-Path $InfraDir 'down.ps1') }
