<#
.SYNOPSIS
Make sure the shared market-research infrastructure is running; start it only if it is not.

.DESCRIPTION
Checks the Postgres, MongoDB and Neo4j containers of ..\Shared-Market-Research-Infra
(override with MARKET_INFRA_DIR). If all three are running, nothing is touched and the
script says so. If any is down, or this project's secrets\ath_scanner.env is missing, it
starts the infra with that project's own up.ps1 (which reuses existing data and accounts).

vLLM holds the GPU, so it is checked separately and only with -Llm.

Exit code 0 when the infra is ready, 1 otherwise. start.ps1 calls this; you can also run it
alone. Stop the infra with stop-infra.ps1; stop.ps1 never touches it.

.PARAMETER Llm    Also make sure the vLLM server is running (started without waiting for its weights to load).
.PARAMETER Status Only report; start nothing.
#>
param(
    [switch]$Llm,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$InfraDir = if ($env:MARKET_INFRA_DIR) { $env:MARKET_INFRA_DIR } else { Join-Path (Split-Path $PSScriptRoot -Parent) 'Shared-Market-Research-Infra' }
$Project  = 'ath_scanner'
$Databases = @('mri-postgres', 'mri-mongo', 'mri-neo4j')

# 'running' | 'healthy' | 'unhealthy' | 'starting' | 'stopped' | 'missing'
function Get-ContainerState([string]$Name) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' $Name 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return 'missing' }
    } finally { $ErrorActionPreference = $previous }
    $status, $health = "$out".Trim() -split '\|'
    if ($status -ne 'running') { return 'stopped' }
    if ($health) { return $health }       # healthy | unhealthy | starting
    return 'running'
}
function Test-Up([string]$State) { return $State -in @('healthy', 'running') }

$previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& docker info --format '{{.ServerVersion}}' *> $null
$dockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previous
if (-not $dockerOk) { Write-Host "Error: Docker is not responding. Start Docker Desktop and retry." -ForegroundColor Red; exit 1 }

$states = [ordered]@{}
foreach ($c in $Databases) { $states[$c] = Get-ContainerState $c }
if ($Llm) { $states['mri-vllm'] = Get-ContainerState 'mri-vllm' }
$secrets = Test-Path -LiteralPath (Join-Path $InfraDir "secrets\$Project.env")

Write-Host "Shared infrastructure ($InfraDir):" -ForegroundColor Cyan
foreach ($k in $states.Keys) { Write-Host ("  {0,-13} {1}" -f $k, $states[$k]) }
Write-Host ("  {0,-13} {1}" -f "$Project.env", $(if ($secrets) { 'present' } else { 'missing' }))

$dbsUp  = -not ($Databases | Where-Object { -not (Test-Up $states[$_]) })
$llmUp  = (-not $Llm) -or (Test-Up $states['mri-vllm'])

if ($dbsUp -and $secrets -and $llmUp) {
    Write-Host "Already running; skipping the infra start." -ForegroundColor Green
    exit 0
}
if ($Status) { Write-Host "Not fully running (status only; nothing started)." -ForegroundColor Yellow; exit 1 }

$up = Join-Path $InfraDir 'up.ps1'
if (-not (Test-Path -LiteralPath $up)) {
    Write-Host "Error: $up not found. Set MARKET_INFRA_DIR or restore that folder." -ForegroundColor Red
    exit 1
}
$upArgs = @{ Project = $Project }
if ($Llm -and -not $llmUp) { $upArgs['Llm'] = $true; $upArgs['NoWait'] = $true }
Write-Host "Starting the infra with $up ..." -ForegroundColor Cyan
Push-Location   # up.ps1 changes directory; put it back afterwards
try { & $up @upArgs } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Host "Error: the infra did not start (see the messages above)." -ForegroundColor Red; exit 1 }
Write-Host "Infra is up." -ForegroundColor Green
exit 0
