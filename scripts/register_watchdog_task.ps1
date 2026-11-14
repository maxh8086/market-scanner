<#
.SYNOPSIS
Register (or remove) the MarketScannerWatchdog Task Scheduler task for the current user.

.DESCRIPTION
Run by you, not by Claude or start.ps1. The task starts scripts\watchdog.ps1 at logon for the
current user, with restart on failure (3 times, 1 minute apart). It runs
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\watchdog.ps1`.

Set WATCHDOG_TOKEN_FILE in your user environment first (outside the repo). The watchdog reads it
from there; this script never reads it.

  -WhatIf       print what would be registered; registers nothing
  -Unregister   remove the task

Examples (run from the repo root):
  .\scripts\register_watchdog_task.ps1 -WhatIf
  .\scripts\register_watchdog_task.ps1
  .\scripts\register_watchdog_task.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Unregister
)

Set-StrictMode -Version Latest

$TaskName = 'MarketScannerWatchdog'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LauncherPath = Join-Path $RepoRoot 'scripts\watchdog.ps1'
$UserId = "$env:USERDOMAIN\$env:USERNAME"

if ($Unregister) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister the scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed scheduled task $TaskName (if it existed)."
    } else {
        Write-Host "WhatIf: would remove scheduled task $TaskName."
    }
    exit 0
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`"" `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, 'Register the scheduled task at logon')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered scheduled task $TaskName for $UserId (at logon, restart 3 times, 1 minute apart)."
} else {
    Write-Host "WhatIf: would register scheduled task $TaskName for $UserId."
    Write-Host "  Trigger : at logon"
    Write-Host "  Action  : powershell.exe -NoProfile -ExecutionPolicy Bypass -File $LauncherPath"
    Write-Host "  Restart : 3 times, 1 minute apart on failure"
    Write-Host "Nothing was registered."
}
