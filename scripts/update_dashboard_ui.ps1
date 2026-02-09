# Dashboard UI Update Helper Script (PowerShell)
# This script helps update remaining dashboard pages with unified navigation

$DASHBOARD_DIR = "shoonya_platform\api\dashboard\web"
$BACKUP_DIR = "shoonya_platform\api\dashboard\web_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Shoonya Dashboard UI Update Helper" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Create backup
Write-Host "[1/4] Creating backup of current dashboard files..." -ForegroundColor Yellow
if (Test-Path $DASHBOARD_DIR) {
    Copy-Item -Path $DASHBOARD_DIR -Destination $BACKUP_DIR -Recurse
    Write-Host "✓ Backup created at: $BACKUP_DIR" -ForegroundColor Green
} else {
    Write-Host "✗ Dashboard directory not found: $DASHBOARD_DIR" -ForegroundColor Red
    exit 1
}
Write-Host ""

# List pages to update
Write-Host "[2/4] Pages to update:" -ForegroundColor Yellow
Write-Host "  - option_chain_dashboard.html"
Write-Host "  - orderbook.html"
Write-Host "  - diagnostics.html"
Write-Host "  - order_diagnostics.html"
Write-Host ""

# Show what will be changed
Write-Host "[3/4] Changes that will be applied:" -ForegroundColor Yellow
Write-Host "  ✓ Update <head> to link common.css" -ForegroundColor Green
Write-Host "  ✓ Replace navigation with unified component" -ForegroundColor Green
Write-Host "  ✓ Add mobile menu toggle function" -ForegroundColor Green
Write-Host "  ✓ Remove references to home.html and strategy_dnss.html" -ForegroundColor Green
Write-Host "  ✓ Update navigation links to /web/ paths" -ForegroundColor Green
Write-Host ""

# Verify strategy page exists
Write-Host "[4/4] Verifying new files..." -ForegroundColor Yellow
if (Test-Path "$DASHBOARD_DIR\strategy.html") {
    Write-Host "✓ strategy.html exists" -ForegroundColor Green
} else {
    Write-Host "✗ strategy.html not found" -ForegroundColor Red
}

if (Test-Path "$DASHBOARD_DIR\styles\common.css") {
    Write-Host "✓ common.css exists" -ForegroundColor Green
} else {
    Write-Host "✗ common.css not found" -ForegroundColor Red
}
Write-Host ""

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Manual Update Steps" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "For each page, make these changes:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. In <head> section, replace inline <style> with:" -ForegroundColor White
Write-Host '   <link rel="stylesheet" href="/web/styles/common.css">' -ForegroundColor Gray
Write-Host ""
Write-Host "2. Replace <header> section with:" -ForegroundColor White
Write-Host '   <header>' -ForegroundColor Gray
Write-Host '       <div class="brand" onclick="window.location.href=''/web/dashboard.html''">◬ Shoonya</div>' -ForegroundColor Gray
Write-Host '       <button class="mobile-menu-toggle" onclick="toggleMobileNav()">☰</button>' -ForegroundColor Gray
Write-Host '       <nav class="nav-links" id="navLinks">' -ForegroundColor Gray
Write-Host '           <a href="/web/dashboard.html" class="nav-link">Dashboard</a>' -ForegroundColor Gray
Write-Host '           <a href="/web/option_chain_dashboard.html" class="nav-link">Option Chain</a>' -ForegroundColor Gray
Write-Host '           <a href="/web/orderbook.html" class="nav-link">Orders</a>' -ForegroundColor Gray
Write-Host '           <a href="/web/place_order.html" class="nav-link">Place Order</a>' -ForegroundColor Gray
Write-Host '           <a href="/web/strategy.html" class="nav-link">Strategy</a>' -ForegroundColor Gray
Write-Host '           <a href="/web/diagnostics.html" class="nav-link">Diagnostics</a>' -ForegroundColor Gray
Write-Host '       </nav>' -ForegroundColor Gray
Write-Host '   </header>' -ForegroundColor Gray
Write-Host ""
Write-Host "3. Add mobile toggle function before </script>:" -ForegroundColor White
Write-Host '   function toggleMobileNav() {' -ForegroundColor Gray
Write-Host '       document.getElementById(''navLinks'').classList.toggle(''mobile-open'');' -ForegroundColor Gray
Write-Host '   }' -ForegroundColor Gray
Write-Host ""
Write-Host "4. Update title format:" -ForegroundColor White
Write-Host '   <title>Page Name | Shoonya Platform</title>' -ForegroundColor Gray
Write-Host ""
Write-Host "5. Set active navigation link:" -ForegroundColor White
Write-Host '   Add class="active" to current page link' -ForegroundColor Gray
Write-Host ""

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Files to Remove (After Testing)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  - home.html (replaced by dashboard.html)"
Write-Host "  - strategy_dnss.html (replaced by strategy.html)"
Write-Host ""

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Testing Checklist" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "After updating pages, test:" -ForegroundColor Yellow
Write-Host "  [ ] Navigation works on desktop"
Write-Host "  [ ] Hamburger menu works on mobile (<768px)"
Write-Host "  [ ] All pages use consistent styling"
Write-Host "  [ ] Links point to correct pages"
Write-Host "  [ ] Strategy page loads correctly"
Write-Host "  [ ] Form submissions still work"
Write-Host "  [ ] Tables are responsive"
Write-Host ""

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Quick Commands" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Preview changes (Python HTTP server):" -ForegroundColor Yellow
Write-Host "  cd shoonya_platform\api\dashboard" -ForegroundColor Gray
Write-Host "  python -m http.server 8080" -ForegroundColor Gray
Write-Host "  # Open http://localhost:8080/web/dashboard.html" -ForegroundColor Gray
Write-Host ""
Write-Host "Or use FastAPI dashboard server:" -ForegroundColor Yellow
Write-Host "  cd shoonya_platform" -ForegroundColor Gray
Write-Host "  python -m uvicorn api.dashboard.app:app --reload --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "Restore from backup (if needed):" -ForegroundColor Yellow
Write-Host "  Remove-Item -Path $DASHBOARD_DIR -Recurse -Force" -ForegroundColor Gray
Write-Host "  Rename-Item -Path $BACKUP_DIR -NewName $DASHBOARD_DIR" -ForegroundColor Gray
Write-Host ""

Write-Host "Backup location: $BACKUP_DIR" -ForegroundColor Green
Write-Host ""
Write-Host "Done! Follow the manual steps above for each page." -ForegroundColor Cyan
