#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Delta Neutral Short Strangle (DNSS) Strategy Service Runner
.DESCRIPTION
    Runs DNSS strategy as a standalone service with proper config loading and graceful shutdown
.EXAMPLE
    .\run_dnss_service.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "ðŸš€ Starting DNSS Strategy Service..." -ForegroundColor Cyan
Write-Host ""

# Get script directory (project root)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Validate prerequisites
Write-Host "ðŸ” Validating prerequisites..." -ForegroundColor Cyan

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
    Write-Host "âŒ Virtual environment not found!" -ForegroundColor Red
    Write-Host "ðŸ‘‰ Run: python bootstrap.py" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".\config_env\primary.env")) {
    Write-Host "âŒ Configuration file not found!" -ForegroundColor Red
    Write-Host "ðŸ‘‰ Create config_env\primary.env with your broker credentials" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
Write-Host "ðŸ”§ Activating virtual environment..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "âŒ Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "âœ… Prerequisites validated" -ForegroundColor Green
Write-Host ""

# Set environment variables
$env:PYTHONUNBUFFERED = "1"
$env:DASHBOARD_ENV = "primary"

# Display service info
# Get config file path (default or from environment variable)
$DNSS_CONFIG = if ($env:DNSS_CONFIG) { $env:DNSS_CONFIG } else { ".\shoonya_platform\\strategy_runner\\saved_configs\dnss_nifty_weekly.json" }

if (-not (Test-Path $DNSS_CONFIG)) {
    Write-Host "âŒ Config file not found: $DNSS_CONFIG" -ForegroundColor Red
    Write-Host "   Set DNSS_CONFIG environment variable or create config at:" -ForegroundColor Yellow
    Write-Host "   .\shoonya_platform\\strategy_runner\\saved_configs\dnss_nifty_weekly.json" -ForegroundColor Yellow
    exit 1
}

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "DNSS STRATEGY SERVICE STARTING" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "ðŸ“Š Strategy: Delta Neutral Short Strangle (DNSS)" -ForegroundColor Yellow
Write-Host "â¹ï¸  Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host "ðŸ“‹ Config: $DNSS_CONFIG" -ForegroundColor Yellow
Write-Host "ðŸ” Broker: config_env\primary.env" -ForegroundColor Yellow
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# Run DNSS strategy
try {
    Write-Host "â–¶ï¸  Starting trading service (strategy_runner mode)..." -ForegroundColor Green
    python main.py
}
catch {
    Write-Host ""
    Write-Host "âŒ Service crashed: $_" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ""
    Write-Host "ðŸ›‘ DNSS service stopped" -ForegroundColor Yellow
}


