# Sample GPU metrics from nvidia-smi and write to CSV.
#
# Samples every -IntervalSeconds (default 2) and writes to
# logs/metrics/<run_id>_gpu.csv until a sentinel file appears at
# logs/metrics/<run_id>.stop
#
# CSV format (from nvidia-smi): timestamp,name,power.draw,utilization.gpu,memory.used
#
# Degrades silently if nvidia-smi is absent (prints a message, then exits).

param(
    [string] $RunId,
    [int] $IntervalSeconds = 2
)

if (-not $RunId) {
    Write-Host "Error: -RunId is required"
    exit 1
}

# Check if nvidia-smi exists
$nvidia_smi = & where.exe nvidia-smi 2>$null
if (-not $nvidia_smi) {
    Write-Host "nvidia-smi not found; GPU sampling skipped"
    exit 0
}

# Create logs/metrics directory if needed
$metrics_dir = "logs\metrics"
if (-not (Test-Path $metrics_dir)) {
    New-Item -ItemType Directory -Force -Path $metrics_dir | Out-Null
}

$csv_file = Join-Path $metrics_dir "${RunId}_gpu.csv"
$stop_file = Join-Path $metrics_dir "${RunId}.stop"

# Clean up any old stop file
if (Test-Path $stop_file) {
    Remove-Item $stop_file -Force
}

# Header for the CSV
$header = "timestamp,name,power.draw,utilization.gpu,memory.used"

# Write header
Add-Content -Path $csv_file -Value $header -Encoding UTF8

Write-Host "Sampling GPU metrics every ${IntervalSeconds}s to $csv_file"

$start_time = [System.DateTime]::UtcNow.Ticks / 10000000

while ($true) {
    # Check for stop sentinel file
    if (Test-Path $stop_file) {
        Write-Host "Stop sentinel detected; exiting"
        Remove-Item $stop_file -Force
        exit 0
    }

    # Query nvidia-smi for the metrics
    # Format: timestamp (Unix epoch), name, power.draw (watts, without unit),
    #         utilization.gpu (percent, without %), memory.used (MB, without unit)
    try {
        $output = & $nvidia_smi --query-gpu=timestamp,name,power.draw,utilization.gpu,memory.used `
                                 --format=csv,noheader,nounits 2>$null
        if ($output) {
            foreach ($line in $output) {
                if ($line -and $line.Trim()) {
                    # Convert timestamp from YYYY/MM/DD HH:MM:SS.mmm to Unix epoch
                    # nvidia-smi gives a date+time; we want a numeric timestamp
                    # For now, use current time - it's close enough for sampling intervals
                    $now = [System.DateTime]::UtcNow.Ticks / 10000000
                    $csv_line = "$now,$line"
                    Add-Content -Path $csv_file -Value $csv_line -Encoding UTF8
                }
            }
        }
    } catch {
        Write-Host "Error querying nvidia-smi: $_"
        exit 1
    }

    Start-Sleep -Seconds $IntervalSeconds
}
