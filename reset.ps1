<#
.SYNOPSIS
Wipe Market Scanner's data and start again from scratch. Asks before deleting anything.

.DESCRIPTION
Stops the app and the infra, deletes the infra's database folders, generated passwords and secrets,
and the app's data, output and logs, then runs start.ps1. Model weights are kept (large, re-downloadable).
Other projects sharing the infra lose their databases too, hence the prompt.
#>
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$InfraDir = if ($env:MARKET_INFRA_DIR) { $env:MARKET_INFRA_DIR } else { Join-Path $PSScriptRoot 'infra' }
if ((Read-Host "Delete ALL database data in $InfraDir\data and app data/output/logs? Type YES") -ne 'YES') { Write-Host 'Cancelled.'; exit 0 }
& (Join-Path $PSScriptRoot 'stop.ps1') -Infra
foreach ($p in (Join-Path $InfraDir 'data'), (Join-Path $InfraDir 'secrets'), (Join-Path $InfraDir '.env'),
               (Join-Path $PSScriptRoot 'app\data'), (Join-Path $PSScriptRoot 'app\output'), (Join-Path $PSScriptRoot 'app\logs')) {
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}
& (Join-Path $PSScriptRoot 'start.ps1')
