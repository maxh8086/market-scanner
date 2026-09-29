<#
.SYNOPSIS
Run the whole ATH Scanner pipeline in Docker, start to finish, with no extra switches.

.DESCRIPTION
scan -> enrich (filings, fundamentals, AI extraction on vLLM) -> TimesFM forecasts ->
Neo4j graph load -> per-stock conclusions -> graph purge of expired data -> final
workbook -> cross-check -> portfolio.

Every component is its own container under one docker-compose.yml; this script is the
only thing that runs on the host. No scheduler; you trigger it. data/, output/ and
logs/ are bind-mounted from this folder, so caches survive between runs.

Credentials: .env (Upstox/Kite) is read by docker compose at runtime; this script only
checks that it exists and never opens it. The Neo4j password is generated here into
.env.neo4j (git-ignored) the first time and reused after that.

Needs an NVIDIA GPU with the container runtime (vLLM runs Qwen3-4B-Instruct-2507).
The first run downloads ~8 GB of model weights and the TimesFM checkpoint.

Data retention (how long stored documents are kept before the purge step deletes them)
is set in config/retention.json -- 3 years by default, "purge": false turns it off.

.PARAMETER Symbols        Comma-separated symbols to scan instead of the full index.
.PARAMETER WithLaya       Also start the Laya decision-model service (not used by any stage yet).
.PARAMETER SkipEnrich     Skip enrichment (and the stages that build on it can still use the last enriched file).
.PARAMETER SkipCrosscheck Skip the independent price cross-check.
.PARAMETER SkipPortfolio  Skip the Kite holdings overlay.
.PARAMETER Rebuild        Rebuild images without the cache.

.EXAMPLE
./start.ps1
./start.ps1 -Symbols "INFY,TCS" -SkipPortfolio
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
Set-Location -Path $PSScriptRoot

$ModelName = 'qwen3-4b'                 # SERVED_NAME in docker/vllm/Dockerfile
$VllmUrl   = 'http://vllm:8000'         # as seen from the other containers

# Run docker and return its exit code. Under Windows PowerShell 5.1 a native
# command's stderr becomes an error record, and docker writes ordinary build
# progress to stderr -- so 'Stop' must be relaxed around the call, and success
# judged by the exit code alone.
function Invoke-Docker {
    param([string[]]$DockerArgs)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @DockerArgs | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Write-Stage([string]$Message) { Write-Host ""; Write-Host "=== $Message ===" -ForegroundColor Cyan }
function Stop-Pipeline([string]$Message) {
    Write-Host "Error: $Message" -ForegroundColor Red
    Write-Host "Containers may still be up; run ./stop.ps1 to clean up." -ForegroundColor Yellow
    exit 1
}

# Wait for a container's own healthcheck (the slim images have no curl).
function Wait-Healthy([string]$Container, [int]$Minutes) {
    $deadline = (Get-Date).AddMinutes($Minutes)
    $health = ''
    while ((Get-Date) -lt $deadline) {
        $health = (& docker inspect --format '{{.State.Health.Status}}' $Container 2>$null)
        if ($health -eq 'healthy') { return $true }
        Start-Sleep -Seconds 5
    }
    Write-Host "$Container last health status: '$health'" -ForegroundColor Yellow
    return $false
}

$timings = [ordered]@{}
function Measure-Stage([string]$Name, [scriptblock]$Body) {
    $t = Get-Date
    $code = & $Body
    $timings[$Name] = [int]((Get-Date) - $t).TotalSeconds
    return $code
}

# The graph is an accelerator, never a dependency: exit 3 means Neo4j was unreachable
# and the run carries on without graph facts.
function Invoke-Graph([string]$Name, [string[]]$GraphArgs) {
    $code = Measure-Stage $Name { Invoke-Docker (@('compose', 'run', '--rm', 'graph') + $GraphArgs) }
    if ($code -eq 3) {
        Write-Host "Graph step '$Name' skipped: Neo4j unreachable (a warning, not a failure)." -ForegroundColor Yellow
    } elseif ($code -ne 0) {
        Write-Host "Graph step '$Name' failed (exit $code) -- continuing without it." -ForegroundColor Yellow
    }
}

Write-Stage "Preflight"
$code = Invoke-Docker @('info', '--format', '{{.ServerVersion}}')
if ($code -ne 0) { Stop-Pipeline "Docker is not responding. Start Docker Desktop and retry." }
# Existence only. This script must never read the credentials file.
if (-not (Test-Path -LiteralPath '.env')) {
    Stop-Pipeline ".env not found. Copy .env.example to .env and fill in your credentials."
}
Write-Host ".env present."
# The database password is ours to generate: random, written once, never printed.
if (-not (Test-Path -LiteralPath '.env.neo4j')) {
    $bytes = New-Object byte[] 30
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $password = ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', '').Substring(0, 24)
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env.neo4j'), "NEO4J_AUTH=neo4j/$password`n",
                            (New-Object Text.UTF8Encoding($false)))
    Remove-Variable password, bytes
    Write-Host ".env.neo4j created (generated database password; git-ignored)."
} else {
    Write-Host ".env.neo4j present."
}
$profiles = @()
if ($WithLaya) { $profiles += @('--profile', 'laya') }

Write-Stage "Building images"
$buildArgs = @('compose') + $profiles + @('build')
if ($Rebuild) { $buildArgs += '--no-cache' }
$code = Measure-Stage 'build' { Invoke-Docker $buildArgs }
if ($code -ne 0) { Stop-Pipeline "Docker build failed." }

if ($WithLaya) {
    Write-Stage "Starting Laya (first start downloads weights; this can take several minutes)"
    $code = Invoke-Docker @('compose', '--profile', 'laya', 'up', '-d', 'laya')
    if ($code -ne 0) { Stop-Pipeline "Could not start Laya." }
    if (-not (Wait-Healthy 'ath-laya' 15)) { Stop-Pipeline "Laya did not become healthy within 15 minutes." }
    Write-Host "Laya is healthy on http://127.0.0.1:8000" -ForegroundColor Green
}

# Both services warm up while the scan runs (vLLM loads its weights, ~2-3 minutes once cached).
Write-Stage "Starting Neo4j and vLLM (Qwen3-4B-Instruct-2507; first start downloads ~8 GB)"
$code = Invoke-Docker @('compose', 'up', '-d', 'neo4j', 'vllm')
if ($code -ne 0) { Stop-Pipeline "Could not start neo4j/vllm (is the NVIDIA runtime available to Docker?)." }

Write-Stage "Scan"
$scanArgs = @('compose', 'run', '--rm', 'scanner')
if ($Symbols) { $scanArgs += @('--symbols', $Symbols) }
$code = Measure-Stage 'scan' { Invoke-Docker $scanArgs }
if ($code -ne 0) { Stop-Pipeline "Scan failed (exit $code)." }

Write-Stage "Waiting for vLLM"
if (-not (Wait-Healthy 'ath-vllm' 30)) { Stop-Pipeline "vLLM did not become healthy within 30 minutes. See: docker logs ath-vllm" }
Write-Host "vLLM is healthy on http://127.0.0.1:8001" -ForegroundColor Green

if ($SkipEnrich) {
    Write-Host "Enrichment skipped."
} else {
    Write-Stage "Enrich (filings, fundamentals, AI extraction on vLLM)"
    $enrichArgs = @('compose', 'run', '--rm', 'enrich', '--all',
                    '--llm-url', $VllmUrl, '--llm-model', $ModelName, '--llm-api', 'openai', '--llm-workers', '4')
    $code = Measure-Stage 'enrich' { Invoke-Docker $enrichArgs }
    if ($code -ne 0) { Stop-Pipeline "Enrichment failed (exit $code)." }

    Write-Stage "Enrich with TimesFM forecasts"
    $code = Measure-Stage 'timesfm' { Invoke-Docker @('compose', 'run', '--rm', 'enrich-timesfm') }
    if ($code -ne 0) { Stop-Pipeline "TimesFM enrichment failed (exit $code)." }
}

$haveEnriched = [bool](Get-ChildItem -LiteralPath 'output' -Filter 'ath_enriched_*.csv' -ErrorAction SilentlyContinue)
if (-not $haveEnriched) {
    Write-Host "Graph, conclusions and report skipped: no output/ath_enriched_*.csv to read." -ForegroundColor Yellow
} else {
    Write-Stage "Graph: load filings and extractions into Neo4j"
    Invoke-Graph 'graph-load' @('load')
    Invoke-Graph 'graph-facts' @('facts')

    Write-Stage "Per-stock conclusions"
    $code = Measure-Stage 'conclude' { Invoke-Docker @('compose', 'run', '--rm', 'conclude') }
    if ($code -eq 2) {
        Write-Host "Some conclusions failed -- a warning. Successful ones are in output/ath_conclusions_*.csv" -ForegroundColor Yellow
    } elseif ($code -ne 0) {
        Stop-Pipeline "Conclusions failed (exit $code)."
    }

    Write-Stage "Graph: store conclusions, purge expired data (config/retention.json)"
    Invoke-Graph 'graph-conclusions' @('conclusions')
    Invoke-Graph 'graph-purge' @('purge')
}

Write-Stage "Freeing the GPU and memory (Neo4j data stays in its volume)"
Invoke-Docker @('compose', 'stop', 'vllm', 'neo4j') | Out-Null

if ($haveEnriched) {
    Write-Stage "Final workbook (sheet 1: every stock, sheet 2: summary)"
    $code = Measure-Stage 'report' { Invoke-Docker @('compose', 'run', '--rm', 'report') }
    if ($code -ne 0) { Stop-Pipeline "Final report failed (exit $code)." }
}

if ($SkipCrosscheck) {
    Write-Host "Cross-check skipped."
} else {
    Write-Stage "Cross-check (independent price source)"
    $code = Measure-Stage 'crosscheck' { Invoke-Docker @('compose', 'run', '--rm', 'crosscheck') }
    if ($code -eq 1) {
        Write-Host "Cross-check found DIVERGED symbols -- a warning, not a failure. See output/crosscheck_*.csv" -ForegroundColor Yellow
    } elseif ($code -ne 0) {
        Stop-Pipeline "Cross-check failed (exit $code)."
    }
}

if ($SkipPortfolio) {
    Write-Host "Portfolio skipped."
} else {
    Write-Stage "Portfolio overlay"
    $code = Measure-Stage 'portfolio' { Invoke-Docker @('compose', 'run', '--rm', 'portfolio') }
    if ($code -eq 2) {
        Write-Host "No holdings source (data/holdings.json or KITE_ACCESS_TOKEN) -- skipped, not a failure." -ForegroundColor Yellow
    } elseif ($code -ne 0) {
        Stop-Pipeline "Portfolio failed (exit $code)."
    }
}

Write-Stage "Done"
foreach ($k in $timings.Keys) { Write-Host ("  {0,-17} {1,5} s" -f $k, $timings[$k]) }
Write-Host ""
Write-Host "Newest files in output/:"
Get-ChildItem -LiteralPath 'output' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 8 |
    ForEach-Object { Write-Host ("  output/{0}" -f $_.Name) }
Write-Host ""
Write-Host "Finished. Run ./stop.ps1 to shut the setup down." -ForegroundColor Green
