<#
.SYNOPSIS
    Launch multiple Shoonya trading clients on Windows.

.DESCRIPTION
    Each client runs as a separate Python process with its own:
    - .env file (unique ports, credentials)
    - Log directory (logs/<USER_ID>/)
    - SQLite database  
    - Risk state file

.EXAMPLE
    # Start both clients:
    .\run_multi_client.ps1

    # Start only the second client:
    .\run_multi_client.ps1 -Clients "yeleshwar_a_komarewar"

    # Start only primary:
    .\run_multi_client.ps1 -Clients "primary"
#>

param(
    [string[]]$Clients = @("primary", "yeleshwar_a_komarewar")
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Find Python executable (venv or system)
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Shoonya Multi-Client Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Python: $Python"
Write-Host "Clients: $($Clients -join ', ')"
Write-Host ""

$Jobs = @()

foreach ($client in $Clients) {
    $envFile = "config_env\$client.env"
    $envPath = Join-Path $ProjectRoot $envFile

    if (-not (Test-Path $envPath)) {
        Write-Host "[ERROR] .env file not found: $envPath" -ForegroundColor Red
        continue
    }

    Write-Host "[STARTING] Client: $client ($envFile)" -ForegroundColor Green

    $job = Start-Process -FilePath $Python `
        -ArgumentList "main.py", "--env", $envFile `
        -WorkingDirectory $ProjectRoot `
        -PassThru `
        -NoNewWindow

    $Jobs += @{
        Name = $client
        Process = $job
    }

    Write-Host "  PID: $($job.Id)" -ForegroundColor Yellow
    
    # Brief delay between launches to avoid port race
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " All clients launched!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($j in $Jobs) {
    Write-Host "  $($j.Name): PID $($j.Process.Id)"
}

Write-Host ""
Write-Host "Press Ctrl+C to stop all clients..." -ForegroundColor Yellow

try {
    # Wait for any process to exit
    while ($true) {
        foreach ($j in $Jobs) {
            if ($j.Process.HasExited) {
                Write-Host "[EXITED] $($j.Name) (PID $($j.Process.Id)) - Exit code: $($j.Process.ExitCode)" -ForegroundColor Red
            }
        }
        Start-Sleep -Seconds 5
    }
} finally {
    Write-Host ""
    Write-Host "Stopping all clients..." -ForegroundColor Yellow
    foreach ($j in $Jobs) {
        if (-not $j.Process.HasExited) {
            Stop-Process -Id $j.Process.Id -Force -ErrorAction SilentlyContinue
            Write-Host "  Stopped $($j.Name) (PID $($j.Process.Id))" -ForegroundColor Yellow
        }
    }
    Write-Host "All clients stopped." -ForegroundColor Green
}
