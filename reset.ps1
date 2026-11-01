<#
.SYNOPSIS
Wipe Market Scanner's data and start again from scratch. Asks before deleting anything.

.DESCRIPTION
Stops the containers, deletes this project's database folders (data\mongo, data\postgres,
data\neo4j) and the app's data, output and logs, then runs start.ps1. Model weights are kept
(large, re-downloadable). .env is never deleted: it holds your credentials.
#>
$ErrorActionPreference = 'Continue'  # native tools write progress to stderr; exit codes are checked explicitly
Set-Location -Path $PSScriptRoot
if ((Read-Host "Delete ALL database data in $PSScriptRoot\data\mongo, postgres and neo4j, and app data/output/logs? Type YES") -ne 'YES') { Write-Host 'Cancelled.'; exit 0 }
& (Join-Path $PSScriptRoot 'stop.ps1')
foreach ($p in (Join-Path $PSScriptRoot 'data\mongo'), (Join-Path $PSScriptRoot 'data\postgres'), (Join-Path $PSScriptRoot 'data\neo4j'),
               (Join-Path $PSScriptRoot 'app\data'), (Join-Path $PSScriptRoot 'app\output'), (Join-Path $PSScriptRoot 'app\logs')) {
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}
& (Join-Path $PSScriptRoot 'start.ps1')
