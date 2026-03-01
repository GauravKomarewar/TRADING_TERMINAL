@echo off
REM Test script for strategy endpoints

setlocal enabledelayedexpansion

echo.
echo ========================================
echo Testing Strategy API Endpoints
echo ========================================

set baseUrl=http://localhost:8000/dashboard

echo.
echo 1. Checking saved strategy configs...
set "CONFIGS_DIR=%~dp0..\shoonya_platform\strategies\saved_configs"
if not exist "%CONFIGS_DIR%" (
    echo WARNING: Strategy configs directory not found at %CONFIGS_DIR%
    goto :skip_configs
)
cd /d "%CONFIGS_DIR%"
dir /b *.json 2>nul
if %ERRORLEVEL% EQU 0 (
    echo SUCCESS: Strategy config files found
) else (
    echo WARNING: No strategy config files found
)
:skip_configs

echo.
echo 2. Dashboard Access Instructions:
echo    URL: http://localhost:8000/
if defined TEST_PASSWORD (
    echo    Password: %TEST_PASSWORD%
) else (
    echo    Password: [set TEST_PASSWORD env var]
)
echo.
echo 3. Steps to test per-strategy control:
echo    a) Open browser: http://localhost:8000/
if defined TEST_PASSWORD (
    echo    b) Enter password: %TEST_PASSWORD%
) else (
    echo    b) Enter password: [set TEST_PASSWORD env var]
)
echo    c) Navigate to Strategy tab
echo    d) You should see a table with Start/Stop buttons for each strategy
echo    e) Click Start button to run a specific strategy
echo    f) Logs will appear in the Control Console below
echo.
echo 4. Check these files for logs:
echo    - logs/dashboard.log
echo    - logs/trading_bot.log
echo.
echo Test Complete!
echo.
