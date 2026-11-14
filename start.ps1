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
LOCAL_LLM_URL environment variable (default http://llm-client:8000).
Set LOCAL_LLM_URL before running this script if the server is elsewhere. Enrichment stops with a
clear message if the endpoint is unreachable.

The TimesFM weights are kept in data\huggingface, which is inside this project.

Data retention (how long stored documents are kept before the purge step deletes them)
is set in config/retention.json -- 3 years by default, "purge": false turns it off.

.PARAMETER Symbols        Comma-separated symbols to scan instead of the full index.
.PARAMETER WithLaya       Also start the Laya decision-model service (not used by any stage yet).
.PARAMETER SkipEnrich     Skip enrichment (and the stages that build on it can still use the last enriched file).
.PARAMETER SkipCrosscheck Skip the independent price cross-check.
.PARAMETER SkipPortfolio  Skip the Kite holdings overlay.
.PARAMETER SkipServices   Do not start the UI (http://127.0.0.1:8080), the collector and the server (http://127.0.0.1:8081) afterwards.
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

$ModelName = 'hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K'  # Ollama model tag served on the host
# External LLM endpoint (not part of this project). Override with LOCAL_LLM_URL in the shell.
$VllmUrl   = if ($env:LOCAL_LLM_URL) { $env:LOCAL_LLM_URL } else { 'http://llm-client:8000' }
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

# Run a host python script from the project venv. Same relaxed-error pattern as Invoke-Docker.
# Non-critical callers log a warning on non-zero exit and carry on.
function Invoke-HostPython([string[]]$PyArgs) {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { return 127 }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & .venv\Scripts\python.exe @PyArgs | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# Like Invoke-Docker, but returns the exit code and stdout. $Stdin, when given, is piped to the
# command: the events database stage sends its SQL this way, so no SQL text goes on the command line
# (PowerShell 5.1 drops double quotes passed to native commands).
function Invoke-DockerCapture([string[]]$DockerArgs, [string]$Stdin = $null) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($null -ne $Stdin) { $out = $Stdin | & docker @DockerArgs } else { $out = & docker @DockerArgs }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Out = @($out) }
    } finally {
        $ErrorActionPreference = $previous
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
# Postgres first: start it and wait until healthy before anything else uses it.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'scripts\ensure_postgres.ps1')
if ($LASTEXITCODE -ne 0) { Stop-Pipeline "Postgres is not healthy (see the messages above)." }
$code = Invoke-Docker @('compose', 'up', '-d', '--wait', 'scanner-postgres', 'scanner-mongo', 'scanner-neo4j')
if ($code -ne 0) { Stop-Pipeline "Could not start the project databases (see the messages above)." }

Write-Stage "Scan"
$scanArgs = @('compose', 'run', '--rm', 'scanner')
if ($Symbols) { $scanArgs += @('--symbols', $Symbols) }
$code = Measure-Stage 'scan' { Invoke-Docker $scanArgs }
if ($code -ne 0) { Stop-Pipeline "Scan failed (exit $code)." }

# The scan hand-over is the ath_scan_candidates table. Ask the enrich image for its newest scan:
# exit 0 prints "YYYY-MM-DD <rows>", exit 2 means no rows or Postgres is unreachable.
$latest = Invoke-DockerCapture @('compose', 'run', '-T', '--rm', '--entrypoint', 'python', 'enrich', '-m', 'scanner.ath_scan_store', 'latest')
$latestLine = ("$($latest.Out)").Trim()
$latestMatch = $null
if ($latest.Code -eq 0 -and $latestLine -match '^(\d{4}-\d{2}-\d{2}) (\d+)$') { $latestMatch = $Matches }
# Nothing within range is a normal result: skip the stages that need stocks, still record the run.
$NoStocks = [bool]$latestMatch -and ([int]$latestMatch[2] -eq 0)
if ($NoStocks) {
    Write-Host "The scan found no stocks within range of their ATH: enrichment, conclusions, report, cross-check and portfolio are skipped." -ForegroundColor Yellow
}

# The run's row must exist before the first LLM call is recorded against it.
if ($RecordRun) {
    if ($latestMatch) {
        $script:RunDate = $latestMatch[1]
        $code = Invoke-Python @('record_run.py', '--begin', '--run-id', $RunId, '--date', $script:RunDate)
        if ($code -eq 0) {
            $script:RunBegun = $true
            Write-Host "Run $RunId started for $($script:RunDate)."
            if (-not $NoStocks) { Start-GpuSampler }
        } else {
            Write-Host "Could not open the run in Postgres (exit $code) -- this run will not be recorded." -ForegroundColor Yellow
        }
    } else {
        Write-Host "No ath_scan_candidates rows found -- this run will not be recorded." -ForegroundColor Yellow
    }
} else {
    Write-Host "Subset run (-Symbols): not recorded in Postgres." -ForegroundColor Yellow
}

# Events database (home events, spec 4.5): create it when missing, before the migrate calls below.
# No password is read and .env is not touched. The admin login is the postgres container's own
# POSTGRES_USER; the app login and the events database name come from the scanner container's
# environment (its env_file is .env). The owner is the app login, because on PostgreSQL 15 and later
# a login that does not own a database cannot create tables in public. A failure is a warning.
Write-Stage "Database: create the events database if missing"
$names = Invoke-DockerCapture @('compose', 'run', '-T', '--rm', '--no-deps', '--entrypoint', 'sh', 'scanner', '-c', 'echo $POSTGRES_USER ${POSTGRES_EVENTS_DB:-market_scanner_events}')
$words = @(("$($names.Out)").Trim() -split '\s+' | Where-Object { $_ })
$appLogin = if ($words.Count -ge 1) { $words[0] } else { '' }
$eventsDb = if ($words.Count -ge 2) { $words[1] } else { '' }
$ident = '^[a-z_][a-z0-9_]{0,62}$'
if ($names.Code -ne 0 -or $appLogin -cnotmatch $ident -or $eventsDb -cnotmatch $ident) {
    Write-Host "Events database not checked: could not read the app login and database name from the scanner container (exit $($names.Code)) -- a warning." -ForegroundColor Yellow
} else {
    $psql = @('compose', 'exec', '-T', 'scanner-postgres', 'sh', '-c', 'psql -U $POSTGRES_USER -d postgres -tA -v ON_ERROR_STOP=1 -f -')
    # Precondition: the app login must exist, or the owner clause fails.
    $role = Invoke-DockerCapture $psql "SELECT count(*) FROM pg_roles WHERE rolname = '$appLogin';"
    if ($role.Code -ne 0 -or ("$($role.Out)").Trim() -ne '1') {
        Write-Host "Events database not created: the app login '$appLogin' was not found in Postgres (exit $($role.Code)) -- a warning." -ForegroundColor Yellow
    } else {
        # \gexec runs the generated CREATE only when the database is missing, so a second run changes nothing.
        $create = "SELECT 'CREATE DATABASE $eventsDb OWNER $appLogin' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$eventsDb') \gexec"
        $code = (Invoke-DockerCapture $psql $create).Code
        if ($code -ne 0) {
            Write-Host "Events database create failed (exit $code) -- a warning; the events migrations will fail until this is fixed." -ForegroundColor Yellow
        }
    }
}

# Schema migrations: apply any pending db/migrations/*.sql before the steps that read the new tables.
# Same ENTRYPOINT override as the steps below. Reported as a warning, not a stop, so a migration
# problem does not block the rest of the run (check the message and re-run once it is fixed).
# The scanner image copies db/ at build time (docker/scanner/Dockerfile). The build stage above runs
# on every start, so db/events_migrations/ is in the image here; no separate rebuild is needed.
Write-Stage "Database: apply pending migrations"
$code = Invoke-Docker @('compose', 'run', '--rm', '--entrypoint', 'python', 'scanner', '-m', 'scanner.pg.migrate')
if ($code -ne 0) {
    Write-Host "Migrations failed (exit $code) -- a warning; the schema may be behind until this is fixed." -ForegroundColor Yellow
}
# Events database: its own schema_migrations table (spec 4.5). Same warning-only handling.
$code = Invoke-Docker @('compose', 'run', '--rm', '--entrypoint', 'python', 'scanner', '-m', 'scanner.pg.migrate', '--db', 'events')
if ($code -ne 0) {
    Write-Host "Events database migrations failed (exit $code) -- a warning; the home events tables may be missing until this is fixed." -ForegroundColor Yellow
}

# Collector start-up (M5): register the collector sources and run the first-run watcher. After the
# migrations and before any collector or watchdog start. Warning only, like the steps above.
$code = Invoke-HostPython @('collect.py', 'init')
if ($code -ne 0) {
    Write-Host "collect.py init failed (exit $code) -- a warning; collector sources may not be registered until this is fixed." -ForegroundColor Yellow
}

# Index constituents: non-critical. A failure leaves the last good CSVs and the last loaded rows in place.
Write-Stage "Constituents: refresh index CSVs on the host (non-critical)"
$code = Invoke-HostPython @('scripts\fetch_index_constituents.py')
if ($code -ne 0) {
    Write-Host "Constituent CSV refresh failed (exit $code) -- a warning; the last good CSVs stay in place." -ForegroundColor Yellow
}

Write-Stage "Constituents: load into Postgres (non-critical)"
# The scanner image's ENTRYPOINT is `python ath_scan.py`, so override it the same way Invoke-Python does for enrich.
$code = Invoke-Docker @('compose', 'run', '--rm', '--entrypoint', 'python', 'scanner', '-m', 'scanner.constituent_membership')
if ($code -ne 0) {
    Write-Host "Constituent load failed (exit $code) -- a warning, not a failure." -ForegroundColor Yellow
}

# Index candles: incremental refresh, non-critical. Same ENTRYPOINT override as the constituent load above.
Write-Stage "Index candles: incremental refresh (non-critical)"
$code = Invoke-Docker @('compose', 'run', '--rm', '--entrypoint', 'python', 'scanner', '-m', 'scanner.index_candles', '--incremental')
if ($code -ne 0) {
    Write-Host "Index candle refresh failed (exit $code) -- a warning, not a failure." -ForegroundColor Yellow
}

# Relative strength reads the index candles and constituent_membership, so it runs after both.
Write-Stage "Relative strength: 12-month RS against each stock's index (non-critical)"
$code = Invoke-Docker @('compose', 'run', '--rm', '--entrypoint', 'python', 'scanner', '-m', 'scanner.relative_strength')
if ($code -ne 0) {
    Write-Host "Relative strength failed (exit $code) -- a warning, not a failure." -ForegroundColor Yellow
}

if ($NoStocks) {
    Write-Host "Enrichment skipped: no stocks in range."
} elseif ($SkipEnrich) {
    Write-Host "Enrichment skipped."
} else {
    Write-Stage "Enrich (filings, fundamentals, AI extraction on the LLM server at $VllmUrl)"
    $enrichArgs = @('compose', 'run', '--rm', 'enrich', '--all',
                    '--llm-url', $VllmUrl, '--llm-model', $ModelName, '--llm-workers', '4')
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
    Write-Host "UI, collector and server not started."
} else {
    Write-Stage "Starting the UI, the collector and the server (they keep running until ./stop.ps1)"
    $code = Invoke-Docker @('compose', 'up', '-d', 'ui', 'collector', 'server')
    if ($code -ne 0) { Write-Host "Could not start the UI/collector/server (exit $code) -- a warning." -ForegroundColor Yellow }
    else {
        Write-Host "UI: http://127.0.0.1:8080" -ForegroundColor Green
        Write-Host "Server API: http://127.0.0.1:8081" -ForegroundColor Green
    }

    # Warning only: the collector watchdog is started by the user (scripts\watchdog.ps1), never here.
    $watchdogUp = $false
    try {
        $watchdogMutex = [System.Threading.Mutex]::OpenExisting('Global\MarketScannerWatchdog')
        $watchdogMutex.Dispose()
        $watchdogUp = $true
    } catch {
        $watchdogUp = $false
    }
    if (-not $watchdogUp) {
        $watchdogProcs = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*scanner.watchdog*' })
        $watchdogUp = $watchdogProcs.Count -gt 0
    }
    if (-not $watchdogUp) {
        Write-Host "The collector watchdog is not running. Start it with scripts\watchdog.ps1, or register it at logon with scripts\register_watchdog_task.ps1." -ForegroundColor Yellow
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
Write-Host "Finished. ./stop.ps1 stops this project's containers." -ForegroundColor Green
