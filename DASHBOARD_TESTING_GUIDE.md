# Dashboard Testing Guide

## Quick Verification Steps

### 1. Option Chain Page - Auto-Refresh Test
**URL**: `/dashboard/option-chain`

**Steps**:
1. Open the Option Chain page
2. Select NIFTY and an expiry date
3. Open browser DevTools (F12) → Console
4. You should see: `"Auto-refresh started: 1000ms"`
5. Watch the table values change every ~1 second automatically
6. Data should update smoothly without any manual refresh button click
7. Check Network tab: API calls should happen every 1 second

**Expected Result**: ✅ Data refreshes automatically every second

---

### 2. Option Chain - Execution Type Feature Test
**URL**: `/dashboard/option-chain`

**Steps**:
1. Open Option Chain (NIFTY)
2. Click on any option LTP cell (e.g., a Call LTP)
3. A popup appears
4. Look for new section: "Execution Type" with ENTRY and EXIT buttons
5. ENTRY should be highlighted (blue, opacity 1)
6. EXIT should be faded (gray, opacity 0.5)
7. Click EXIT button
8. EXIT should now be highlighted, ENTRY faded
9. Click Add to Basket
10. Open basket modal (click 🛒 Basket button)
11. In basket item details, you should see execution type displayed
   - Example: "BUY EXIT | 1 Lots (Qty 50) | MIS | LIMIT @ ₹..."
12. Try changing execution type between ENTRY/EXIT multiple times
13. Submit order and verify in browser Network tab that execution_type is sent

**Expected Result**: ✅ Execution type selector works, values propagate to API

---

### 3. Dashboard Main Page - Holdings Table Test
**URL**: `/dashboard/home`

**Steps**:
1. Open Dashboard
2. Scroll down to "Holdings" table
3. Verify columns display: Symbol | LTP | Net PnL | Realized PnL | Unrealized PnL | Exchange | Product | Qty | Avg Price
4. Check that:
   - **Symbol**: Shows trading symbol (e.g., INFY, RELIANCE)
   - **LTP**: Shows latest trade price as ₹ currency
   - **Net PnL**: Shows total P&L in green (positive) or red (negative)
   - **Product**: Shows CNC, MIS, or NRML
   - **Qty**: Shows quantity as number
   - **Avg Price**: Shows average entry price as ₹ currency
5. Watch the table for 5+ seconds
6. LTP and PnL values should update automatically
7. Compare with "Positions" table layout - should be identical structure

**Expected Result**: ✅ Holdings display all required data with proper formatting

---

### 4. Dashboard - Auto-Refresh Test
**URL**: `/dashboard/home`

**Steps**:
1. Open Dashboard
2. Open browser DevTools (F12) → Network tab
3. Filter for XHR requests
4. Watch for requests to `/dashboard/home/status`
5. Requests should occur every ~1 second
6. Check one response - should have holdings, positions, system status
7. Values in tables should update smoothly without full refresh
8. Positions table: PnL values should update frequently
9. Holdings table: Values should update frequently
10. No page reload should ever happen - smooth continuous updates

**Expected Result**: ✅ Data refreshes every 1 second, values update smoothly

---

### 5. Diagnostics Page - UI and Auto-Refresh Test
**URL**: `/dashboard/diagnostics`

**Steps**:

#### UI Consistency Check
1. Open Diagnostics page
2. Compare with other pages (Dashboard, Option Chain)
   - Font should be clean sans-serif (not monospace) ✅
   - Colors should match dashboard theme (dark background, blue accents) ✅
   - Spacing and padding should look consistent ✅
3. Check readability:
   - Headings (h1, h2, h3) should be clear and properly sized ✅
   - Info cards should have proper padding and borders ✅
   - Status badges should be easy to read ✅

#### Auto-Refresh Functionality
1. Open DevTools → Console
2. You should see: `"Auto-refresh started: 1000ms"`
3. Check "Dashboard Status (Live)" section
   - Status should say: ✓ Auto-refreshing every 1s
4. Watch the pre block for "dashboardResult"
5. Data should update every ~1 second
6. Check Network tab: requests to `/dashboard/home/status` every 1 second
7. "Order Pipeline Diagnostics" section should update every second
8. "Intent Verification" section should update every second
9. Test endpoints work:
   - Select symbol in dropdown
   - Click "Test Expiries" button
   - Click "Test Option Chain" button
   - Results should display in pre blocks

**Expected Result**: ✅ UI consistent, everything auto-refreshes at 1 second interval

---

### 6. Place Order Page - Execution Type Verification
**URL**: `/dashboard/place-order`

**Steps**:
1. Open Place Order page
2. Look at "Manual Order" card
3. Find "Execution" dropdown
4. Verify options: ENTRY, EXIT, TEST ENTRY (S), TEST ENTRY (F), TEST EXIT (S), TEST EXIT (F)
5. Select different execution types
6. Fill in a sample order:
   - Exchange: NFO
   - Symbol: NIFTY
   - Side: BUY
   - Execution: EXIT
   - Qty: 50
   - Product: MIS
   - Order Type: MARKET
7. Click "Add to Basket"
8. Check basket section - execution type should be stored
9. Submit basket and verify execution_type parameter in network request

**Expected Result**: ✅ Execution type selector works and submits correctly

---

## Advanced Testing

### Performance Test
**Objective**: Verify no memory leaks or performance degradation

**Steps**:
1. Open Option Chain page
2. Open DevTools → Performance tab
3. Open DevTools → Memory tab (or Task Manager → Memory)
4. Let page run for 2+ minutes
5. Take heap snapshot at 1 min mark
6. Take heap snapshot at 2 min mark
7. Compare snapshots - memory growth should be minimal
8. Check Network tab - requests should be consistent every 1 second
9. CPU usage should be low (DevTools → Performance)

**Expected Result**: ✅ No memory leaks, consistent memory usage

---

### Cross-Browser Test
**Objective**: Verify all pages work in different browsers

**Browsers to Test**:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)
- [ ] Chrome Mobile (iOS)
- [ ] Safari Mobile (iOS)

**Steps** (per browser):
1. Navigate to `/dashboard/home`
2. Take screenshot
3. Navigate to `/dashboard/option-chain`
4. Take screenshot
5. Navigate to `/dashboard/diagnostics`
6. Take screenshot
7. Verify:
   - Layout looks correct
   - No rendering issues
   - Auto-refresh working (check Network tab)
   - Responsive on mobile

**Expected Result**: ✅ Works consistently across all modern browsers

---

### Real-Time Data Verification
**Objective**: Verify data accuracy and real-time updates

**Steps**:
1. Open Dashboard + Option Chain in two browser tabs
2. Have market data open in a third source
3. Compare Option Chain LTP with market data
4. Values should match within seconds
5. Verify option Greeks update in real-time:
   - Delta, Gamma, Theta, Vega should change as spot price moves
   - OI should update when trades occur
6. Compare Dashboard PnL with external source
7. Verify execution type is correctly stored:
   - Place ENTRY order
   - Place EXIT order
   - Verify they execute as intended

**Expected Result**: ✅ Data stays current and accurate

---

## Troubleshooting

### Issue: Auto-refresh not working
**Debug Steps**:
1. Open DevTools Console
2. Should see: "Auto-refresh started: 1000ms"
3. If not seen, check:
   - Page fully loaded
   - No JavaScript errors
   - Cookies/session valid
4. Check Network tab for API calls (should see every 1 second)
5. If no API calls, might be:
   - CORS issue (check console errors)
   - API endpoint down
   - Authentication expired

### Issue: Execution type not appearing
**Debug Steps**:
1. Open DevTools Elements tab
2. Search for `orderExecEntry`
3. If not found: JavaScript didn't load properly
4. Check Console for errors
5. Verify HTML contains the new buttons
6. Check CSS for visibility (opacity should not be hidden)

### Issue: Holdings table showing wrong data
**Debug Steps**:
1. Open DevTools Network tab
2. Check `/dashboard/home/status` response
3. Look for `holdings` array in response
4. Verify field names in response:
   - Check for: tsym, symbol, tradingsymbol, itemcode
   - Should have at least one of these
5. If fields missing, broker API might have changed
6. Check JavaScript console for parsing errors

### Issue: Diagnostics not refreshing
**Debug Steps**:
1. Check Console for: "Auto-refresh started: 1000ms"
2. If not present, check for JavaScript errors
3. Verify `/dashboard/diagnostics` endpoint exists
4. Check Network tab for API calls
5. If API calls fail, verify authentication

---

## Verification Checklist

### Functionality
- [ ] Option Chain page auto-refreshes every 1 second
- [ ] Execution type selector appears in order popup
- [ ] ENTRY/EXIT selection works with visual feedback
- [ ] Basket displays execution type
- [ ] API receives correct execution_type parameter
- [ ] Dashboard holdings table shows all required columns
- [ ] Holdings data displays with proper formatting
- [ ] Dashboard auto-refreshes every 1 second
- [ ] Diagnostics page auto-refreshes every 1 second
- [ ] Diagnostics UI consistent with dashboard theme

### UI/UX
- [ ] All fonts are consistent (not monospace on diagnostics)
- [ ] Colors match dashboard theme
- [ ] Spacing and padding look professional
- [ ] All pages are responsive on mobile
- [ ] No visual glitches or rendering issues
- [ ] Tables scroll smoothly
- [ ] Buttons have proper hover states
- [ ] Form inputs are clearly labeled

### Performance
- [ ] Page loads in < 2 seconds
- [ ] Auto-refresh doesn't cause lag
- [ ] Memory usage stable over time
- [ ] CPU usage low during idle times
- [ ] Network requests consistent every 1 second
- [ ] No console errors

### Data Accuracy
- [ ] Symbols display correctly
- [ ] LTP values are current
- [ ] PnL calculations are accurate
- [ ] Greeks (Delta, Gamma, Theta, Vega) update in real-time
- [ ] Status badges reflect current state
- [ ] Execution types are preserved through order flow

---

## Sign-Off

Once all tests pass, the dashboard is ready for production:

✅ **All pages tested and verified**
✅ **Auto-refresh working at 1 second intervals**
✅ **Execution type feature fully functional**
✅ **UI consistent across all pages**
✅ **No console errors or warnings**
✅ **Data accuracy verified**
✅ **Performance acceptable**

**Ready for deployment!**

---

Date: 2026-02-10
Tester: ______________________
