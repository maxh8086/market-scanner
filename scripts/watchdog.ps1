<#
.SYNOPSIS
Run the collector watchdog (python -m scanner.watchdog) in this session.

.DESCRIPTION
Thin launcher. Only one watchdog runs at a time: a named mutex (Global\MarketScannerWatchdog)
is taken, and a second copy exits with 0 and a message. The working directory is the repo root.

WATCHDOG_TOKEN_FILE must name the host file that holds the watchdog's bearer token (outside the
repo). It is taken from the environment, or from the user-level environment variable of the same
name. This script never reads .env and never prints the path or the token.

The watchdog runs until it is stopped (Ctrl+C, or the Task Scheduler task ends). Its exit code is
passed on. Logs go to logs\watchdog.log.

To register it at logon, run scripts\register_watchdog_task.ps1 yourself. Claude and start.ps1
never start or register it.
#>
Set-StrictMode -Version Latest

$MutexName = 'Global\MarketScannerWatchdog'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Watchdog {
    $tokenFile = $env:WATCHDOG_TOKEN_FILE
    if ([string]::IsNullOrWhiteSpace($tokenFile)) {
        $tokenFile = [Environment]::GetEnvironmentVariable('WATCHDOG_TOKEN_FILE', 'User')
    }
    if ([string]::IsNullOrWhiteSpace($tokenFile)) {
        Write-Host 'WATCHDOG_TOKEN_FILE is not set (environment or user environment variable). Not started.' -ForegroundColor Red
        return 2
    }
    $env:WATCHDOG_TOKEN_FILE = $tokenFile

    $python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'The project virtualenv is missing (.venv\Scripts\python.exe). Not started.' -ForegroundColor Red
        return 2
    }

    Set-Location -LiteralPath $RepoRoot
    & $python -m scanner.watchdog
    return $LASTEXITCODE
}

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($false, $MutexName, [ref]$createdNew)
$exitCode = 0
if (-not $createdNew) {
    Write-Host 'The collector watchdog is already running. Nothing to do.' -ForegroundColor Yellow
    $mutex.Dispose()
    exit 0
}
try {
    $exitCode = Invoke-Watchdog
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
exit $exitCode
