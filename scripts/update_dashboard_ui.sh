#!/bin/bash

# Dashboard UI Update Helper Script
# This script helps update remaining dashboard pages with unified navigation

DASHBOARD_DIR="shoonya_platform/api/dashboard/web"
BACKUP_DIR="shoonya_platform/api/dashboard/web_backup_$(date +%Y%m%d_%H%M%S)"

echo "================================================"
echo "  Shoonya Dashboard UI Update Helper"
echo "================================================"
echo ""

# Create backup
echo "[1/4] Creating backup of current dashboard files..."
if [ -d "$DASHBOARD_DIR" ]; then
    cp -r "$DASHBOARD_DIR" "$BACKUP_DIR"
    echo "✓ Backup created at: $BACKUP_DIR"
else
    echo "✗ Dashboard directory not found: $DASHBOARD_DIR"
    exit 1
fi
echo ""

# List pages to update
echo "[2/4] Pages to update:"
echo "  - option_chain_dashboard.html"
echo "  - orderbook.html"
echo "  - diagnostics.html"
echo "  - order_diagnostics.html"
echo ""

# Show what will be changed
echo "[3/4] Changes that will be applied:"
echo "  ✓ Update <head> to link common.css"
echo "  ✓ Replace navigation with unified component"
echo "  ✓ Add mobile menu toggle function"
echo "  ✓ Remove references to home.html and strategy_dnss.html"
echo "  ✓ Update navigation links to /web/ paths"
echo ""

# Verify strategy page exists
echo "[4/4] Verifying new files..."
if [ -f "$DASHBOARD_DIR/strategy.html" ]; then
    echo "✓ strategy.html exists"
else
    echo "✗ strategy.html not found"
fi

if [ -f "$DASHBOARD_DIR/styles/common.css" ]; then
    echo "✓ common.css exists"
else
    echo "✗ common.css not found"
fi
echo ""

echo "================================================"
echo "  Manual Update Steps"
echo "================================================"
echo ""
echo "For each page, make these changes:"
echo ""
echo "1. In <head> section, replace inline <style> with:"
echo "   <link rel=\"stylesheet\" href=\"/web/styles/common.css\">"
echo ""
echo "2. Replace <header> section with:"
echo "   <header>"
echo "       <div class=\"brand\" onclick=\"window.location.href='/web/dashboard.html'\">◬ Shoonya</div>"
echo "       <button class=\"mobile-menu-toggle\" onclick=\"toggleMobileNav()\">☰</button>"
echo "       <nav class=\"nav-links\" id=\"navLinks\">"
echo "           <a href=\"/web/dashboard.html\" class=\"nav-link\">Dashboard</a>"
echo "           <a href=\"/web/option_chain_dashboard.html\" class=\"nav-link\">Option Chain</a>"
echo "           <a href=\"/web/orderbook.html\" class=\"nav-link\">Orders</a>"
echo "           <a href=\"/web/place_order.html\" class=\"nav-link\">Place Order</a>"
echo "           <a href=\"/web/strategy.html\" class=\"nav-link\">Strategy</a>"
echo "           <a href=\"/web/diagnostics.html\" class=\"nav-link\">Diagnostics</a>"
echo "       </nav>"
echo "   </header>"
echo ""
echo "3. Add mobile toggle function before </script>:"
echo "   function toggleMobileNav() {"
echo "       document.getElementById('navLinks').classList.toggle('mobile-open');"
echo "   }"
echo ""
echo "4. Update title format:"
echo "   <title>Page Name | Shoonya Platform</title>"
echo ""
echo "5. Set active navigation link:"
echo "   Add class=\"active\" to current page link"
echo ""

echo "================================================"
echo "  Files to Remove (After Testing)"
echo "================================================"
echo ""
echo "  - home.html (replaced by dashboard.html)"
echo "  - strategy_dnss.html (replaced by strategy.html)"
echo ""

echo "================================================"
echo "  Testing Checklist"
echo "================================================"
echo ""
echo "After updating pages, test:"
echo "  [ ] Navigation works on desktop"
echo "  [ ] Hamburger menu works on mobile (<768px)"
echo "  [ ] All pages use consistent styling"
echo "  [ ] Links point to correct pages"
echo "  [ ] Strategy page loads correctly"
echo "  [ ] Form submissions still work"
echo "  [ ] Tables are responsive"
echo ""

echo "================================================"
echo "  Quick Commands"
echo "================================================"
echo ""
echo "Preview changes:"
echo "  cd shoonya_platform/api/dashboard"
echo "  python -m http.server 8080"
echo "  # Open http://localhost:8080/web/dashboard.html"
echo ""
echo "Restore from backup (if needed):"
echo "  rm -rf $DASHBOARD_DIR"
echo "  mv $BACKUP_DIR $DASHBOARD_DIR"
echo ""

echo "Backup location: $BACKUP_DIR"
echo ""
echo "Done! Follow the manual steps above for each page."
