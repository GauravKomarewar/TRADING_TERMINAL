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

Write-Host "🚀 Starting DNSS Strategy Service..." -ForegroundColor Cyan
Write-Host ""

# Get script directory (project root)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Validate prerequisites
Write-Host "🔍 Validating prerequisites..." -ForegroundColor Cyan

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
    Write-Host "❌ Virtual environment not found!" -ForegroundColor Red
    Write-Host "👉 Run: python bootstrap.py" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".\config_env\primary.env")) {
    Write-Host "❌ Configuration file not found!" -ForegroundColor Red
    Write-Host "👉 Create config_env\primary.env with your broker credentials" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Prerequisites validated" -ForegroundColor Green
Write-Host ""

# Set environment variables
$env:PYTHONUNBUFFERED = "1"
$env:DASHBOARD_ENV = "primary"

# Display service info
# Get config file path (default or from environment variable)
$DNSS_CONFIG = if ($env:DNSS_CONFIG) { $env:DNSS_CONFIG } else { ".\shoonya_platform\strategies\saved_configs\dnss_nifty_weekly.json" }

if (-not (Test-Path $DNSS_CONFIG)) {
    Write-Host "❌ Config file not found: $DNSS_CONFIG" -ForegroundColor Red
    Write-Host "   Set DNSS_CONFIG environment variable or create config at:" -ForegroundColor Yellow
    Write-Host "   .\shoonya_platform\strategies\saved_configs\dnss_nifty_weekly.json" -ForegroundColor Yellow
    exit 1
}

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "DNSS STRATEGY SERVICE STARTING" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "📊 Strategy: Delta Neutral Short Strangle (DNSS)" -ForegroundColor Yellow
Write-Host "⏹️  Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host "📋 Config: $DNSS_CONFIG" -ForegroundColor Yellow
Write-Host "🔐 Broker: config_env\primary.env" -ForegroundColor Yellow
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# Run DNSS strategy
try {
    Write-Host "▶️  Starting DNSS strategy execution..." -ForegroundColor Green
    python -m shoonya_platform.strategies.delta_neutral --config "$DNSS_CONFIG"
}
catch {
    Write-Host ""
    Write-Host "❌ Service crashed: $_" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ""
    Write-Host "🛑 DNSS service stopped" -ForegroundColor Yellow
}
