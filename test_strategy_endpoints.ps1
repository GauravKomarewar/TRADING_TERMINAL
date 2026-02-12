# Test script for strategy endpoints
# This tests the per-strategy start/stop endpoints

Write-Host "Testing Strategy API Endpoints" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

# Base URL
$baseUrl = "http://localhost:8000/dashboard"

Write-Host "`n1. Testing GET /strategy/list endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/strategy/list" -Method Get -ErrorAction Stop
    $result = $response.Content | ConvertFrom-Json
    Write-Host "✓ SUCCESS: Found $($result.total) strategies" -ForegroundColor Green
    Write-Host "Strategies: $($result.strategies | ConvertTo-Json -Depth 1)" -ForegroundColor Gray
} catch {
    Write-Host "✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n2. Testing /runner/status endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/runner/status" -Method Get -ErrorAction Stop
    $result = $response.Content | ConvertFrom-Json
    Write-Host "✓ SUCCESS: Runner status retrieved" -ForegroundColor Green
    Write-Host "   is_running: $($result.is_running)" -ForegroundColor Gray
    Write-Host "   strategies_active: $($result.strategies_active)" -ForegroundColor Gray
} catch {
    Write-Host "✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n3. List saved strategy configs..." -ForegroundColor Yellow
$configDir = "c:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform\shoonya_platform\strategies\saved_configs"
$configs = Get-ChildItem -Path $configDir -Filter "*.json" -ErrorAction SilentlyContinue
if ($configs) {
    Write-Host "✓ Found $(($configs | Measure-Object).Count) strategy config files:" -ForegroundColor Green
    $configs | ForEach-Object { Write-Host "   - $($_.BaseName)" -ForegroundColor Gray }
} else {
    Write-Host "✗ No strategy config files found in $configDir" -ForegroundColor Red
}

Write-Host "`n4. Dashboard Login Details" -ForegroundColor Yellow
Write-Host "   URL: http://localhost:8000/" -ForegroundColor Gray
Write-Host "   Password: 1234" -ForegroundColor Gray

Write-Host "`n5. Next Steps:" -ForegroundColor Cyan
Write-Host "   a) Open browser and go to http://localhost:8000/" -ForegroundColor Gray
Write-Host "   b) Enter password: 1234" -ForegroundColor Gray
Write-Host "   c) Click 'Strategy' tab" -ForegroundColor Gray
Write-Host "   d) You should see Start/Stop buttons for each strategy" -ForegroundColor Gray
Write-Host "   e) Click 'Start' to run a specific strategy" -ForegroundColor Gray
Write-Host "   f) Logs will appear in the Control Console" -ForegroundColor Gray

Write-Host "`nTest Complete!`n" -ForegroundColor Cyan
