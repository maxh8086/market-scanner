<#
.SYNOPSIS
Run the whole Market Scanner pipeline in Docker, start to finish, with no extra switches.

.DESCRIPTION
scan -> enrich (filings, fundamentals, AI extraction on the LLM server) -> TimesFM forecasts ->
Neo4j graph load -> per-stock conclusions -> graph purge of expired data -> final
workbook -> cross-check -> portfolio -> record the run in Postgres -> start the UI and the
collector.

Postgres, MongoDB and Neo4j are this project's own containers (scanner-postgres, scanner-mongo,
scanner-neo4j); this script starts them with the rest of the compose services. stop.ps1 stops them.

Each run gets a run id. Its row is created right after the scan (so every LLM call can be
tagged with it), GPU power is sampled while the model is loaded, and at the end the snapshots,
changes, token counts, timings and GPU energy are written to Postgres for the UI's Cost
center. Recording is best effort: if Postgres is unreachable the pipeline still finishes.
A run restricted with -Symbols is never recorded, so it cannot replace the day's full run.

Every component is its own container under one docker-compose.yml; this script is the
only thing that runs on the host. No scheduler; you trigger it. data/, output/ and
logs/ are bind-mounted from this folder, so caches survive between runs.

Credentials: .env (Upstox/Kite and the database logins) is read by docker compose at runtime;
this script only checks that it exists and never opens it.

The LLM server is not started by this project. It is an OpenAI-compatible endpoint given by the
LLM_URL environment variable (default http://host.docker.internal:8000, the host's port 8000).
Set LLM_URL before running this script if the server is elsewhere. Enrichment stops with a
clear message if the endpoint is unreachable.

The TimesFM weights are kept in data\huggingface, which is inside this project.

Data retention (how long stored documents are kept before the purge step deletes them)
is set in config/retention.json -- 3 years by default, "purge": false turns it off.

.PARAMETER Symbols        Comma-separated symbols to scan instead of the full index.
.PARAMETER WithLaya       Also start the Laya decision-model service (not used by any stage yet).
.PARAMETER SkipEnrich     Skip enrichment (and the stages that build on it can still use the last enriched file).
.PARAMETER SkipCrosscheck Skip the independent price cross-check.
.PARAMETER SkipPortfolio  Skip the Kite holdings overlay.
.PARAMETER SkipServices   Do not start the UI (http://127.0.0.1:8080) and the collector afterwards.
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
    [switch]$SkipServices,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$ModelName = 'qwen3-4b'                 # model name the external OpenAI-compatible LLM server serves
# External LLM endpoint (not part of this project). Override with LLM_URL in the shell.
$VllmUrl   = if ($env:LLM_URL) { $env:LLM_URL } else { 'http://host.docker.internal:8000' }
$RunId     = [guid]::NewGuid().ToString()
$env:RUN_ID = $RunId                    # docker-compose.yml passes it to scanner, enrich and conclude
$RecordRun = -not $Symbols              # a subset run must not replace the day's full run
$script:RunDate = $null                 # set after the scan
$script:RunBegun = $false
$script:Sampler = $null

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

# Run a python script inside the enrich image (it has the database clients and the code).
function Invoke-Python([string[]]$PyArgs) {
    return Invoke-Docker (@('compose', 'run', '--rm', '--entrypoint', 'python', 'enrich') + $PyArgs)
}

# Sample GPU power beside the run so the Cost center can report energy. Silent without nvidia-smi.
function Start-GpuSampler {
    try {
        $script:Sampler = Start-Process -FilePath 'powershell.exe' -PassThru -WindowStyle Hidden `
            -WorkingDirectory $PSScriptRoot `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\gpu_sample.ps1', '-RunId', $RunId)
    } catch {
        Write-Host "GPU sampling not started: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
function Stop-GpuSampler {
    if (-not $script:Sampler) { return }
    $dir = Join-Path $PSScriptRoot 'logs\metrics'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    New-Item -ItemType File -Force -Path (Join-Path $dir "$RunId.stop") | Out-Null
    if (-not $script:Sampler.WaitForExit(15000)) { Stop-Process -Id $script:Sampler.Id -Force -ErrorAction SilentlyContinue }
    $script:Sampler = $null
}

function Write-Stage([string]$Message) { Write-Host ""; Write-Host "=== $Message ===" -ForegroundColor Cyan }
function Stop-Pipeline([string]$Message) {
    Write-Host "Error: $Message" -ForegroundColor Red
    Stop-GpuSampler
    if ($script:RunBegun) {
        Invoke-Python @('record_run.py', '--run-id', $RunId, '--date', $script:RunDate, '--fail') | Out-Null
    }
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

Write-Stage "Databases (Postgres, MongoDB, Neo4j)"
$code = Invoke-Docker @('compose', 'up', '-d', '--wait', 'scanner-postgres', 'scanner-mongo', 'scanner-neo4j')
if ($code -ne 0) { Stop-Pipeline "Could not start the project databases (see the messages above)." }

Write-Stage "Scan"
$scanArgs = @('compose', 'run', '--rm', 'scanner')
if ($Symbols) { $scanArgs += @('--symbols', $Symbols) }
$code = Measure-Stage 'scan' { Invoke-Docker $scanArgs }
if ($code -ne 0) { Stop-Pipeline "Scan failed (exit $code)." }

$newest = Get-ChildItem -LiteralPath 'output' -Filter 'ath_scan_*.csv' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
# Nothing within range is a normal result: skip the stages that need stocks, still record the run.
$NoStocks = [bool]$newest -and (@(Import-Csv -LiteralPath $newest.FullName).Count -eq 0)
if ($NoStocks) {
    Write-Host "The scan found no stocks within range of their ATH: enrichment, conclusions, report, cross-check and portfolio are skipped." -ForegroundColor Yellow
}

# The run's row must exist before the first LLM call is recorded against it.
if ($RecordRun) {
    if ($newest -and $newest.BaseName -match '(\d{4}-\d{2}-\d{2})$') {
        $script:RunDate = $Matches[1]
        $code = Invoke-Python @('record_run.py', '--begin', '--run-id', $RunId, '--date', $script:RunDate)
        if ($code -eq 0) {
            $script:RunBegun = $true
            Write-Host "Run $RunId started for $($script:RunDate)."
            if (-not $NoStocks) { Start-GpuSampler }
        } else {
            Write-Host "Could not open the run in Postgres (exit $code) -- this run will not be recorded." -ForegroundColor Yellow
        }
    } else {
        Write-Host "No output/ath_scan_<date>.csv found -- this run will not be recorded." -ForegroundColor Yellow
    }
} else {
    Write-Host "Subset run (-Symbols): not recorded in Postgres." -ForegroundColor Yellow
}

if ($NoStocks) {
    Write-Host "Enrichment skipped: no stocks in range."
} elseif ($SkipEnrich) {
    Write-Host "Enrichment skipped."
} else {
    Write-Stage "Enrich (filings, fundamentals, AI extraction on the LLM server at $VllmUrl)"
    $enrichArgs = @('compose', 'run', '--rm', 'enrich', '--all',
                    '--llm-url', $VllmUrl, '--llm-model', $ModelName, '--llm-api', 'openai', '--llm-workers', '4')
    $code = Measure-Stage 'enrich' { Invoke-Docker $enrichArgs }
    if ($code -ne 0) { Stop-Pipeline "Enrichment failed (exit $code)." }

    Write-Stage "Enrich with TimesFM forecasts"
    $code = Measure-Stage 'timesfm' { Invoke-Docker @('compose', 'run', '--rm', 'enrich-timesfm') }
    if ($code -ne 0) { Stop-Pipeline "TimesFM enrichment failed (exit $code)." }
}

$haveEnriched = (-not $NoStocks) -and [bool](Get-ChildItem -LiteralPath 'output' -Filter 'ath_enriched_*.csv' -ErrorAction SilentlyContinue)
if ($NoStocks) {
    # already reported above
} elseif (-not $haveEnriched) {
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

Stop-GpuSampler

if ($haveEnriched) {
    Write-Stage "Final workbook (sheet 1: every stock, sheet 2: summary)"
    $code = Measure-Stage 'report' { Invoke-Docker @('compose', 'run', '--rm', 'report') }
    if ($code -ne 0) { Stop-Pipeline "Final report failed (exit $code)." }
}

if ($NoStocks) {
    Write-Host "Cross-check skipped: no stocks in range."
} elseif ($SkipCrosscheck) {
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

if ($NoStocks) {
    Write-Host "Portfolio skipped: no stocks in range."
} elseif ($SkipPortfolio) {
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

if ($script:RunBegun) {
    Write-Stage "Recording the run (snapshots, changes, tokens, timings, GPU energy)"
    $code = Invoke-Python @('record_run.py', '--run-id', $RunId, '--date', $script:RunDate)
    if ($code -ne 0) { Write-Host "Recording the run failed (exit $code) -- a warning; the files in output/ are complete." -ForegroundColor Yellow }
    # Windows PowerShell 5.1 drops the quotes inside a native argument, so escape them.
    $timingsJson = ($timings | ConvertTo-Json -Compress).Replace('"', '\"')
    $gpuCsv = "logs/metrics/${RunId}_gpu.csv"
    $code = Invoke-Python @('-m', 'scanner.metrics', 'finalize', '--run-id', $RunId, '--gpu-csv', $gpuCsv, '--timings', $timingsJson)
    if ($code -ne 0) { Write-Host "Cost metrics not finalized (exit $code) -- a warning." -ForegroundColor Yellow }
}

if ($SkipServices) {
    Write-Host "UI and collector not started."
} else {
    Write-Stage "Starting the UI and the collector (they keep running until ./stop.ps1)"
    $code = Invoke-Docker @('compose', 'up', '-d', 'ui', 'collector')
    if ($code -ne 0) { Write-Host "Could not start the UI/collector (exit $code) -- a warning." -ForegroundColor Yellow }
    else { Write-Host "UI: http://127.0.0.1:8080" -ForegroundColor Green }
}

Write-Stage "Done"
foreach ($k in $timings.Keys) { Write-Host ("  {0,-17} {1,5} s" -f $k, $timings[$k]) }
Write-Host ""
Write-Host "Newest files in output/:"
Get-ChildItem -LiteralPath 'output' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 8 |
    ForEach-Object { Write-Host ("  output/{0}" -f $_.Name) }
Write-Host ""
Write-Host "Finished. ./stop.ps1 stops this project's containers." -ForegroundColor Green
