#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Shoonya Platform Windows Service Runner
.DESCRIPTION
    Simple PowerShell script to run Shoonya platform as a background process on Windows.
    For production use, consider NSSM (see SERVICE_INSTALLATION_WINDOWS.md)
.EXAMPLE
    .\run_windows_service.ps1
#>

# Activate virtual environment and run main.py
$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting Shoonya Trading Platform..." -ForegroundColor Cyan
Write-Host ""

# Get script directory (project root)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Check if venv exists
if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
    Write-Host "❌ Virtual environment not found!" -ForegroundColor Red
    Write-Host "👉 Run: python bootstrap.py" -ForegroundColor Yellow
    exit 1
}

# Check if config exists
if (-not (Test-Path ".\config_env\primary.env")) {
    Write-Host "❌ Configuration file not found!" -ForegroundColor Red
    Write-Host "👉 Create config_env\primary.env with your credentials" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Project root: $ProjectRoot" -ForegroundColor Green
Write-Host "✅ Config found: config_env\primary.env" -ForegroundColor Green
Write-Host ""

# Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

# Set environment variables
$env:PYTHONUNBUFFERED = "1"

Write-Host "✅ Virtual environment activated" -ForegroundColor Green
Write-Host ""

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "STARTING SHOONYA PLATFORM" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "📊 Dashboard will be available at: http://localhost:8000" -ForegroundColor Yellow
Write-Host "🔗 Execution service on: http://localhost:5001" -ForegroundColor Yellow
Write-Host "⏹️  Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# Run main.py
try {
    python main.py
}
catch {
    Write-Host ""
    Write-Host "❌ Service crashed: $_" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ""
    Write-Host "🛑 Service stopped" -ForegroundColor Yellow
}
