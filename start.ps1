<#
.SYNOPSIS
Start Market Scanner on any machine with Git and Docker: clones what is missing, then starts everything.

.DESCRIPTION
1. Clones the shared infra (Postgres, MongoDB, Neo4j, vLLM) into .\infra if it is not there.
   Set MARKET_INFRA_DIR to reuse an infra checkout you already have (shared with other projects).
2. Clones the application source into .\app if it is not there.
3. Downloads the model weights on first run (about 9 GB), then starts the infra with the
   market_scanner database logins. Neo4j and vLLM are part of the default start.
4. Builds and starts the app (UI on http://127.0.0.1:8080). API keys are entered in the UI the first time.

Safe to re-run; existing clones, data and passwords are reused. Start over: .\reset.ps1.

.PARAMETER NoLlm   Skip vLLM (no GPU, or the LLM comes from elsewhere). Neo4j still starts.
.PARAMETER Update  git pull the infra and app clones before starting.
#>
param([switch]$NoLlm, [switch]$Update)

$ErrorActionPreference = 'Continue'  # native tools write progress to stderr; exit codes are checked explicitly
Set-Location -Path $PSScriptRoot

$InfraRepo = 'https://github.com/maxh8086/shared-market-research-Infra.git'
$AppRepo   = 'https://github.com/maxh8086/ATH-Scanner.git'
$InfraDir  = if ($env:MARKET_INFRA_DIR) { $env:MARKET_INFRA_DIR } else { Join-Path $PSScriptRoot 'infra' }
$AppDir    = Join-Path $PSScriptRoot 'app'
$env:MARKET_INFRA_DIR = $InfraDir
$Project   = 'market_scanner'

function Fail([string]$m) { Write-Host "Error: $m" -ForegroundColor Red; exit 1 }
function Step([string]$m) { Write-Host ""; Write-Host "=== $m ===" -ForegroundColor Cyan }

foreach ($tool in 'git', 'docker') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool is not installed or not on PATH." }
}
$prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& docker info *> $null; $dockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prev
if (-not $dockerOk) { Fail 'Docker is not running. Start Docker and retry.' }

function Sync-Repo([string]$Url, [string]$Dir) {
    if (-not (Test-Path -LiteralPath (Join-Path $Dir '.git'))) {
        if ((Test-Path -LiteralPath $Dir) -and (Get-ChildItem -LiteralPath $Dir -Force | Select-Object -First 1)) {
            Fail "$Dir exists, is not empty and is not a git clone."
        }
        Write-Host "Cloning $Url -> $Dir"
        & git clone $Url $Dir
        if ($LASTEXITCODE -ne 0) { Fail "git clone $Url failed." }
    } elseif ($Update) {
        Write-Host "Updating $Dir"
        & git -C $Dir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Fail "git pull in $Dir failed." }
    }
}

Step 'Source'
Sync-Repo $InfraRepo $InfraDir
Sync-Repo $AppRepo $AppDir

Step 'Shared infra'
$hub = Join-Path $InfraDir 'models\huggingface\hub'
$haveWeights = (Test-Path -LiteralPath $hub) -and (Get-ChildItem -LiteralPath $hub -Directory -Filter 'models--*' -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $NoLlm -and -not $haveWeights) {
    Write-Host 'First run: downloading model weights (about 9 GB)...'
    & (Join-Path $InfraDir 'models.ps1')
    if ($LASTEXITCODE -ne 0) { Fail 'Model download failed.' }
}
$up = @{ Project = $Project }
if (-not $NoLlm) { $up['Llm'] = $true }
& (Join-Path $InfraDir 'up.ps1') @up
if ($LASTEXITCODE -ne 0) { Fail 'The shared infra did not start.' }

Step 'Market Scanner'
Set-Location -Path $PSScriptRoot  # up.ps1 changes directory
& docker compose up -d --build ui collector
if ($LASTEXITCODE -ne 0) { Fail 'docker compose up failed.' }

Write-Host ""
Write-Host 'Market Scanner is up: http://127.0.0.1:8080  (first visit asks for your API keys)' -ForegroundColor Green
