# QUICK FIX GUIDE
## Critical Bug Fixes for Trading System

---

## FIX #1: STRATEGY.HTML - CLOSED LEGS DISAPPEARING 🔴

### Priority: IMMEDIATE (1 hour)

### The Problem:
Closed legs disappear from the UI after being exited because:
1. The `collapseBySymbol()` function overwrites CLOSED status with ACTIVE
2. Closed legs are being aggregated when they should show individually

### The Fix:

#### Step 1: Update Line 1038 (Don't Collapse Closed Legs)

**File:** `/api/dashboard/web/strategy.html`

**Find (around line 1038):**
```javascript
${renderMonitorTable(collapseBySymbol(closedRowsRaw))}
```

**Replace with:**
```javascript
${renderMonitorTable(closedRowsRaw)}
```

**Reason:** Closed legs should show individual exit prices, not aggregated.

---

#### Step 2: Update Line 1076 (Completed Strategies)

**File:** `/api/dashboard/web/strategy.html`

**Find (around line 1076):**
```javascript
${renderMonitorTable(collapseBySymbol(closedRowsRaw))}
```

**Replace with:**
```javascript
${renderMonitorTable(closedRowsRaw)}
```

---

#### Step 3: Fix collapseBySymbol() Status Merging (Around Line 891)

**File:** `/api/dashboard/web/strategy.html`

**Find (around lines 880-892):**
```javascript
    x.delta = Number(x.delta || 0) + Number(p.delta || 0);
    x.gamma = Number(x.gamma || 0) + Number(p.gamma || 0);
    x.theta = Number(x.theta || 0) + Number(p.theta || 0);
    x.vega = Number(x.vega || 0) + Number(p.vega || 0);

    if (x.side && p.side && x.side !== p.side) x.side = 'MIXED';
    if (!x.side && p.side) x.side = p.side;
    if (!x.owner && p.owner) x.owner = p.owner;
    if (!x.source && (p.source || p.position_source)) x.source = p.source || p.position_source;
    if (x.exit_price == null && p.exit_price != null) x.exit_price = p.exit_price;
    if ((x.entry_price ?? x.avg_price) == null && (p.entry_price ?? p.avg_price) != null) {
      x.entry_price = p.entry_price;
      x.avg_price = p.avg_price;
    }
    if (x.ltp == null && p.ltp != null) x.ltp = p.ltp;
    if (!x.status && p.status) x.status = p.status;
```

**Replace with (add CLOSED status priority):**
```javascript
    x.delta = Number(x.delta || 0) + Number(p.delta || 0);
    x.gamma = Number(x.gamma || 0) + Number(p.gamma || 0);
    x.theta = Number(x.theta || 0) + Number(p.theta || 0);
    x.vega = Number(x.vega || 0) + Number(p.vega || 0);

    if (x.side && p.side && x.side !== p.side) x.side = 'MIXED';
    if (!x.side && p.side) x.side = p.side;
    if (!x.owner && p.owner) x.owner = p.owner;
    if (!x.source && (p.source || p.position_source)) x.source = p.source || p.position_source;
    if (x.exit_price == null && p.exit_price != null) x.exit_price = p.exit_price;
    if ((x.entry_price ?? x.avg_price) == null && (p.entry_price ?? p.avg_price) != null) {
      x.entry_price = p.entry_price;
      x.avg_price = p.avg_price;
    }
    if (x.ltp == null && p.ltp != null) x.ltp = p.ltp;
    
    // FIX: Always preserve CLOSED status (highest priority)
    if (p.status === 'CLOSED' || String(p.status).toUpperCase() === 'CLOSED') {
      x.status = 'CLOSED';
    } else if (!x.status && p.status) {
      x.status = p.status;
    }
```

---

### Testing the Fix:

```bash
# 1. Start the system
# 2. Run a strategy until entry
# 3. Exit one leg (it should appear in "Closed Legs")
# 4. Exit another leg
# 5. Verify both legs remain visible in "Closed Legs"
# 6. Refresh the page
# 7. Confirm closed legs are still visible
```

### Expected Behavior After Fix:
- ✅ Closed legs show in "Closed Legs" section
- ✅ Each closed leg shows its individual exit price
- ✅ Closed legs persist after page refresh
- ✅ Active and closed legs don't mix
- ✅ No legs disappear

---

## FIX #2: STRATEGY_BUILDER.HTML - FLOWCHART DETAILS 🟡

### Priority: MEDIUM (2 hours)

### The Problem:
The flowchart shows simplified action summaries that don't include important details like:
- Match leg parameters
- Strike offsets
- New leg configurations

### The Fix:

#### Update _adjActionSummary() Function (Around Line 1941)

**File:** `/api/dashboard/web/strategy_builder.html`

**Find (around lines 1941-1957):**
```javascript
function _adjActionSummary(card, adjId, branch, actionType){
  const detail = card.querySelector(`#adj_${branch}_detail_${adjId}`) || card;
  const q = sel => detail.querySelector(sel);
  if(actionType==='close_leg') return `Close ${q('[data-role="close-leg-sel"]')?.value || 'selected leg'}`;
  if(actionType==='partial_close_lots') return `Partial close ${q('[data-role="partial-leg-sel"]')?.value || 'selected leg'} (${q('[data-role="partial-lots"]')?.value || '1'} lot)`;
  if(actionType==='reduce_by_pct') return `Reduce ${q('[data-role="reduce-leg-sel"]')?.value || 'selected leg'} by ${q('[data-role="reduce-pct"]')?.value || '50'}%`;
  if(actionType==='roll_to_next_expiry') return `Roll ${q('[data-role="roll-leg-sel"]')?.value || 'selected leg'} to ${q('[data-role="roll-target-expiry"]')?.value || 'weekly_next'}`;
  if(actionType==='open_hedge') return 'Open hedge leg';
  if(actionType==='convert_to_spread') return 'Convert into spread (add wing)';
  if(actionType==='simple_close_open_new'){
    const swaps = [...(detail.querySelectorAll(`#swaps_${branch}_${adjId} .swap-card`) || [])];
    if(!swaps.length) return 'Close/Open (swap)';
    const tags = swaps.map(sc=>sc.querySelector('[data-role="swap-close"]')?.value || 'leg').join(', ');
    return `Swap ${swaps.length} leg(s): ${_shortTxt(tags, 70)}`;
  }
  return _actionLabel(actionType);
}
```

**Replace with (enhanced details):**
```javascript
function _adjActionSummary(card, adjId, branch, actionType){
  const detail = card.querySelector(`#adj_${branch}_detail_${adjId}`) || card;
  const q = sel => detail.querySelector(sel);
  
  if(actionType==='close_leg') {
    return `Close ${q('[data-role="close-leg-sel"]')?.value || 'selected leg'}`;
  }
  
  if(actionType==='partial_close_lots') {
    return `Partial close ${q('[data-role="partial-leg-sel"]')?.value || 'selected leg'} (${q('[data-role="partial-lots"]')?.value || '1'} lot)`;
  }
  
  if(actionType==='reduce_by_pct') {
    return `Reduce ${q('[data-role="reduce-leg-sel"]')?.value || 'selected leg'} by ${q('[data-role="reduce-pct"]')?.value || '50'}%`;
  }
  
  if(actionType==='roll_to_next_expiry') {
    const leg = q('[data-role="roll-leg-sel"]')?.value || 'selected leg';
    const target = q('[data-role="roll-target-expiry"]')?.value || 'weekly_next';
    const same = q('[data-role="roll-same-strike"]')?.value || 'yes';
    return `Roll ${leg} to ${target} (${same === 'yes' ? 'same strike' : same})`;
  }
  
  if(actionType==='open_hedge') {
    return 'Open hedge leg';
  }
  
  if(actionType==='convert_to_spread') {
    return 'Convert into spread (add wing)';
  }
  
  if(actionType==='simple_close_open_new'){
    const swaps = [...(detail.querySelectorAll(`#swaps_${branch}_${adjId} .swap-card`) || [])];
    if(!swaps.length) return 'Close/Open (swap)';
    
    // Build detailed swap descriptions
    const swapDetails = swaps.map(sc => {
      const closeTag = sc.querySelector('[data-role="swap-close"]')?.value || 'leg';
      const side = sc.querySelector('[data-role*="side"]')?.value || '';
      const optType = sc.querySelector('[data-role*="opt-type"]')?.value || '';
      const strikeMode = sc.querySelector('[data-role*="strike-mode"]')?.value || '';
      const strikeSel = sc.querySelector('[data-role*="strike-sel"]')?.value || '';
      const matchLeg = sc.querySelector('[data-role*="match-leg"]')?.value || '';
      const matchParam = sc.querySelector('[data-role*="match-param"]')?.value || '';
      const matchOffset = sc.querySelector('[data-role*="match-offset"]')?.value || '';
      
      let newLegDesc = '';
      if (side && optType) {
        newLegDesc = `${side} ${optType}`;
        
        if (strikeMode === 'match_leg' && matchLeg) {
          newLegDesc += ` matching ${matchLeg}`;
          if (matchParam) {
            newLegDesc += ` ${matchParam}`;
          }
          if (matchOffset && matchOffset !== '0') {
            newLegDesc += ` ${matchOffset > 0 ? '+' : ''}${matchOffset}`;
          }
        } else if (strikeSel) {
          newLegDesc += ` @ ${strikeSel}`;
        }
      }
      
      return newLegDesc ? `${closeTag} → ${newLegDesc}` : closeTag;
    });
    
    const fullDesc = swapDetails.join(', ');
    return `Swap: ${_shortTxt(fullDesc, 150)}`;
  }
  
  return _actionLabel(actionType);
}
```

### Testing the Fix:

```bash
# 1. Open strategy_builder.html
# 2. Create adjustment rule with simple_close_open_new
# 3. Configure: Close LOWER_DELTA_LEG, Open new leg matching HIGHER_DELTA_LEG delta
# 4. Switch to Flowchart tab
# 5. Verify adjustment shows: "Swap: LOWER_DELTA_LEG → SELL CE matching HIGHER_DELTA_LEG abs_delta"
```

### Expected Behavior After Fix:
- ✅ Flowchart shows which leg is closing
- ✅ Flowchart shows new leg configuration
- ✅ Flowchart shows match parameters
- ✅ Flowchart shows strike offsets
- ✅ More informative for complex adjustments

---

## OPTIONAL ENHANCEMENTS

### Enhancement 1: Add Color Coding to Flowchart

**File:** `/api/dashboard/web/strategy_builder.html`

**Add CSS (around line 300):**
```css
.fc-adj-swap-close {
  color: var(--danger);
  font-weight: 600;
}

.fc-adj-swap-arrow {
  color: var(--muted);
  margin: 0 4px;
}

.fc-adj-swap-new {
  color: var(--success);
  font-weight: 600;
}
```

**Update swap rendering in _adjActionSummary:**
```javascript
return `Swap: <span class="fc-adj-swap-close">${closeTag}</span><span class="fc-adj-swap-arrow">→</span><span class="fc-adj-swap-new">${newLegDesc}</span>`;
```

---

### Enhancement 2: Show Individual Closed Leg Timestamps

**File:** `/api/dashboard/web/strategy.html`

**Add column in renderMonitorTable (around line 920):**
```javascript
<th>Exit Time</th>
```

**Add data in tbody (around line 945):**
```javascript
<td>${p.exit_timestamp ? new Date(p.exit_timestamp).toLocaleTimeString() : '-'}</td>
```

---

## VALIDATION CHECKLIST

After applying fixes, verify:

- [ ] Closed legs appear in strategy.html "Closed Legs" section
- [ ] Closed legs persist after page refresh
- [ ] Individual exit prices are shown (not aggregated)
- [ ] No legs disappear when closing positions
- [ ] Flowchart shows match leg parameters
- [ ] Flowchart shows strike offsets
- [ ] Flowchart shows new leg configurations
- [ ] All adjustment types render correctly in flowchart

---

## FILES TO MODIFY

```
/api/dashboard/web/strategy.html (3 changes)
  - Line 891: Fix status merging
  - Line 1038: Remove collapseBySymbol for closed legs
  - Line 1076: Remove collapseBySymbol for completed strategies

/api/dashboard/web/strategy_builder.html (1 change)
  - Lines 1941-1957: Enhance _adjActionSummary function
```

---

## BACKUP BEFORE APPLYING FIXES

```bash
# Backup files before modification
cp /api/dashboard/web/strategy.html /api/dashboard/web/strategy.html.backup
cp /api/dashboard/web/strategy_builder.html /api/dashboard/web/strategy_builder.html.backup
```

---

## ROLLBACK IF NEEDED

```bash
# If issues occur, restore backups
mv /api/dashboard/web/strategy.html.backup /api/dashboard/web/strategy.html
mv /api/dashboard/web/strategy_builder.html.backup /api/dashboard/web/strategy_builder.html
```

---

*Quick Fix Guide Generated: February 25, 2026*
*Estimated Total Time: 3 hours*
*Risk Level: LOW (localized changes, easily reversible)*
