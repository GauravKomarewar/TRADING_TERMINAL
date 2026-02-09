# Shoonya Platform - PowerShell Profile Setup (Windows)
# ======================================================
# This script adds 'shoonya-clean' command to your PowerShell session
#
# USAGE:
# 1. One-time setup (adds to PowerShell profile):
#    .\setup_powershell_commands.ps1 -Install
#
# 2. Current session only:
#    . .\setup_powershell_commands.ps1
# ======================================================

param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"

# Get project root
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CleanupScript = Join-Path $ProjectRoot "shoonya_platform\tools\cleanup_shoonya_platform.py"
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"

# Define the shoonya-clean function
function shoonya-clean {
    <#
    .SYNOPSIS
        Shoonya Platform cleanup utility
    .DESCRIPTION
        Removes __pycache__ directories and .pyc files, optionally restarts services
    #>
    & $VenvPython $CleanupScript @args
}

if ($Install) {
    # Install to PowerShell profile
    Write-Host "📝 Installing shoonya-clean command to PowerShell profile..." -ForegroundColor Cyan
    
    # Get profile path
    if (-not (Test-Path $PROFILE)) {
        New-Item -Path $PROFILE -ItemType File -Force | Out-Null
        Write-Host "✅ Created PowerShell profile: $PROFILE" -ForegroundColor Green
    }
    
    # Check if already installed
    $profileContent = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($profileContent -like "*shoonya-clean*") {
        Write-Host "ℹ️  Command already installed in profile" -ForegroundColor Yellow
    } else {
        # Add function to profile
        $functionCode = @"

# Shoonya Platform Commands
# Auto-added by setup_powershell_commands.ps1
function shoonya-clean {
    `$ProjectRoot = "$ProjectRoot"
    `$VenvPython = Join-Path `$ProjectRoot "venv\Scripts\python.exe"
    `$CleanupScript = Join-Path `$ProjectRoot "shoonya_platform\tools\cleanup_shoonya_platform.py"
    & `$VenvPython `$CleanupScript `$args
}
"@
        Add-Content -Path $PROFILE -Value $functionCode
        Write-Host "✅ Added shoonya-clean command to profile" -ForegroundColor Green
        Write-Host ""
        Write-Host "👉 Restart PowerShell or run:" -ForegroundColor Yellow
        Write-Host "   . `$PROFILE" -ForegroundColor Cyan
    }
} else {
    # Just define function for current session
    Write-Host "✅ shoonya-clean command available in current session" -ForegroundColor Green
    Write-Host "👉 Usage: shoonya-clean" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To install permanently, run:" -ForegroundColor Yellow
    Write-Host "   .\setup_powershell_commands.ps1 -Install" -ForegroundColor Cyan
}

# Export the function
Export-ModuleMember -Function shoonya-clean
