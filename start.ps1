<#
.SYNOPSIS
Manually run the ATH Scanner pipeline in Docker: scan -> enrich -> crosscheck -> portfolio.

.DESCRIPTION
No scheduler; you trigger it. Data, output and logs are bind-mounted from this
folder, so caches survive between runs. Credentials are read by docker compose
from .env at runtime; this script only checks that the file exists and never
opens it. Run stop.ps1 when you are done.

.PARAMETER Symbols        Comma-separated symbols to scan instead of the full index.
.PARAMETER WithLlm        Start an Ollama container and run enrichment with --llm (first start pulls the model, several GB).
.PARAMETER WithLaya       Also start the Laya decision-model service (first start downloads ~800 MB of weights). Not used by any stage yet.
.PARAMETER WithTimesfm    After enrichment, re-run the report with the TimesFM forecaster (separate torch image; first run downloads the 200M checkpoint).
.PARAMETER WithConclusions Start the vLLM container (Qwen3-4B-Instruct-2507, NVIDIA GPU required; first start downloads ~8 GB) and write a per-stock conclusion from the stored insights.
.PARAMETER SkipEnrich     Skip enrichment.
.PARAMETER SkipCrosscheck Skip the independent price cross-check.
.PARAMETER SkipPortfolio  Skip the Kite holdings overlay.
.PARAMETER Rebuild        Rebuild images without the cache.

.EXAMPLE
./start.ps1
./start.ps1 -Symbols "INFY,TCS" -SkipPortfolio
#>
param(
    [string]$Symbols,
    [switch]$WithLlm,
    [switch]$WithLaya,
    [switch]$WithTimesfm,
    [switch]$WithConclusions,
    [switch]$SkipEnrich,
    [switch]$SkipCrosscheck,
    [switch]$SkipPortfolio,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$LlmModel = 'qwen3:8b'   # keep in step with scanner/llm.py LLMConfig.model

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

Write-Stage "Preflight"
$code = Invoke-Docker @('info', '--format', '{{.ServerVersion}}')
if ($code -ne 0) { Stop-Pipeline "Docker is not responding. Start Docker Desktop and retry." }
# Existence only. This script must never read the credentials file.
if (-not (Test-Path -LiteralPath '.env')) {
    Stop-Pipeline ".env not found. Copy .env.example to .env and fill in your credentials."
}
Write-Host ".env present."

$profiles = @()
if ($WithLlm)  { $profiles += @('--profile', 'llm') }
if ($WithLaya) { $profiles += @('--profile', 'laya') }
if ($WithTimesfm) { $profiles += @('--profile', 'timesfm') }
if ($WithConclusions) { $profiles += @('--profile', 'vllm') }

Write-Stage "Building images"
$buildArgs = @('compose') + $profiles + @('build')
if ($Rebuild) { $buildArgs += '--no-cache' }
$code = Measure-Stage 'build' { Invoke-Docker $buildArgs }
if ($code -ne 0) { Stop-Pipeline "Docker build failed." }

if ($WithLlm) {
    Write-Stage "Starting the extraction model (Ollama, $LlmModel)"
    $code = Invoke-Docker @('compose', '--profile', 'llm', 'up', '-d', 'llm')
    if ($code -ne 0) { Stop-Pipeline "Could not start the llm container." }
    # No healthcheck on the stock image; retry the pull until the server is up.
    $pulled = $false
    for ($i = 0; $i -lt 30 -and -not $pulled; $i++) {
        $code = Invoke-Docker @('exec', 'ath-llm', 'ollama', 'pull', $LlmModel)
        if ($code -eq 0) { $pulled = $true } else { Start-Sleep -Seconds 5 }
    }
    if (-not $pulled) { Stop-Pipeline "Could not pull model $LlmModel." }
}

if ($WithLaya) {
    Write-Stage "Starting Laya (first start downloads weights; this can take several minutes)"
    $code = Invoke-Docker @('compose', '--profile', 'laya', 'up', '-d', 'laya')
    if ($code -ne 0) { Stop-Pipeline "Could not start Laya." }
    if (-not (Wait-Healthy 'ath-laya' 15)) { Stop-Pipeline "Laya did not become healthy within 15 minutes." }
    Write-Host "Laya is healthy on http://127.0.0.1:8000" -ForegroundColor Green
}

Write-Stage "Scan"
$scanArgs = @('compose', 'run', '--rm', 'scanner')
if ($Symbols) { $scanArgs += @('--symbols', $Symbols) }
$code = Measure-Stage 'scan' { Invoke-Docker $scanArgs }
if ($code -ne 0) { Stop-Pipeline "Scan failed (exit $code)." }

if ($SkipEnrich) {
    Write-Host "Enrichment skipped."
} else {
    Write-Stage "Enrich"
    $enrichArgs = @('compose') + $profiles + @('run', '--rm', 'enrich', '--all')
    if ($WithLlm) { $enrichArgs += @('--llm', '--llm-url', 'http://llm:11434', '--llm-model', $LlmModel) }
    $code = Measure-Stage 'enrich' { Invoke-Docker $enrichArgs }
    if ($code -ne 0) { Stop-Pipeline "Enrichment failed (exit $code)." }
}

if ($WithTimesfm) {
    if ($SkipEnrich) {
        Write-Host "TimesFM skipped (it re-runs the enrichment report)."
    } else {
        Write-Stage "Enrich with TimesFM forecasts"
        $code = Measure-Stage 'timesfm' { Invoke-Docker @('compose', '--profile', 'timesfm', 'run', '--rm', 'enrich-timesfm') }
        if ($code -ne 0) { Stop-Pipeline "TimesFM enrichment failed (exit $code)." }
    }
}

if ($WithConclusions) {
    if ($SkipEnrich -and -not (Get-ChildItem -LiteralPath 'output' -Filter 'ath_enriched_*.csv' -ErrorAction SilentlyContinue)) {
        Write-Host "Conclusions skipped: no output/ath_enriched_*.csv to read." -ForegroundColor Yellow
    } else {
        Write-Stage "Starting vLLM (Qwen3-4B-Instruct-2507; first start downloads ~8 GB and compiles kernels)"
        $code = Invoke-Docker @('compose', '--profile', 'vllm', 'up', '-d', 'vllm')
        if ($code -ne 0) { Stop-Pipeline "Could not start vLLM (is the NVIDIA runtime available to Docker?)." }
        if (-not (Wait-Healthy 'ath-vllm' 30)) { Stop-Pipeline "vLLM did not become healthy within 30 minutes. See: docker logs ath-vllm" }
        Write-Host "vLLM is healthy on http://127.0.0.1:8001" -ForegroundColor Green
        Write-Stage "Per-stock conclusions"
        $code = Measure-Stage 'conclude' { Invoke-Docker @('compose', '--profile', 'vllm', 'run', '--rm', 'conclude') }
        if ($code -eq 2) {
            Write-Host "Some conclusions failed -- a warning. Successful ones are in output/ath_conclusions_*.csv" -ForegroundColor Yellow
        } elseif ($code -ne 0) {
            Stop-Pipeline "Conclusions failed (exit $code)."
        }
    }
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
foreach ($k in $timings.Keys) { Write-Host ("  {0,-11} {1,5} s" -f $k, $timings[$k]) }
Write-Host ""
Write-Host "Newest files in output/:"
Get-ChildItem -LiteralPath 'output' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 8 |
    ForEach-Object { Write-Host ("  output/{0}" -f $_.Name) }
Write-Host ""
Write-Host "Finished. Run ./stop.ps1 to shut the setup down." -ForegroundColor Green
