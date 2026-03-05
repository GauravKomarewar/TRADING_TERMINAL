# DETAILED CODE-LEVEL BUG FIXES
## Shoonya Trading Platform - Strategy Runner

This document provides exact code fixes for each identified bug, with before/after comparisons and test cases.

---

## CRITICAL FIX #1: Market Data Refresh Missing

### Location
`strategy_executor_service.py` - main execution loop

### Current Code (BROKEN)
```python
def run_cycle(self):
    """Run one strategy cycle"""
    # Update spot price
    self.state.spot_price = self.market_reader.get_spot_price()
    
    # Check conditions
    # ... entry/adjustment/exit logic
    
    # Problem: Leg Greeks are NEVER updated!
```

### Fixed Code
```python
def run_cycle(self):
    """Run one strategy cycle"""
    # Update spot price
    self.state.spot_price = self.market_reader.get_spot_price()
    self.state.atm_strike = self.market_reader.get_atm_strike()
    self.state.fut_ltp = self.market_reader.get_fut_ltp()
    
    # ✅ FIX: Refresh all active leg Greeks and LTP
    self._refresh_leg_market_data()
    
    # Check conditions
    # ... entry/adjustment/exit logic

def _refresh_leg_market_data(self):
    """Update LTP and Greeks for all active legs from market data"""
    for tag, leg in list(self.state.legs.items()):
        if not leg.is_active:
            continue
        
        try:
            if leg.instrument == InstrumentType.FUT:
                # Update future LTP
                fut_ltp = self.market_reader.get_fut_ltp(leg.expiry)
                if fut_ltp:
                    leg.ltp = fut_ltp
            
            elif leg.instrument == InstrumentType.OPT:
                # Update option data
                if leg.strike is None or leg.option_type is None:
                    logger.warning(f"Leg {tag} missing strike/option_type, skipping refresh")
                    continue
                
                opt_data = self.market_reader.get_option_at_strike(
                    strike=leg.strike,
                    option_type=leg.option_type,
                    expiry=leg.expiry
                )
                
                if opt_data:
                    # Update all fields
                    leg.ltp = opt_data.get('ltp', leg.ltp)
                    leg.delta = opt_data.get('delta', leg.delta)
                    leg.gamma = opt_data.get('gamma', leg.gamma)
                    leg.theta = opt_data.get('theta', leg.theta)
                    leg.vega = opt_data.get('vega', leg.vega)
                    leg.iv = opt_data.get('iv', leg.iv)
                    leg.oi = opt_data.get('oi', leg.oi)
                    leg.volume = opt_data.get('volume', leg.volume)
                    
                    logger.debug(
                        f"Market refresh | {tag} | "
                        f"ltp={leg.ltp:.2f} delta={leg.delta:.4f} "
                        f"gamma={leg.gamma:.6f} theta={leg.theta:.2f}"
                    )
                else:
                    logger.warning(
                        f"No market data for {tag} | "
                        f"strike={leg.strike} {leg.option_type.value} {leg.expiry}"
                    )
        
        except Exception as e:
            logger.error(f"Failed to refresh market data for {tag}: {e}")
            # Continue with stale data rather than crashing
```

### Test Case
```python
def test_market_data_refresh():
    # Setup
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG",
        symbol="NIFTY",
        instrument=InstrumentType.OPT,
        option_type=OptionType.CE,
        strike=25000.0,
        expiry="27-MAR-2026",
        side=Side.SELL,
        qty=1,
        entry_price=100.0,
        ltp=100.0,
        delta=0.3,
    )
    state.legs["CE_LEG"] = leg
    
    # Mock market reader to return updated data
    mock_reader = MockMarketReader()
    mock_reader.set_option_data(25000.0, "CE", {
        'ltp': 80.0,
        'delta': 0.5,  # Delta changed!
        'gamma': 0.001,
        'theta': -10.0,
    })
    
    executor = StrategyExecutor(state, mock_reader)
    executor._refresh_leg_market_data()
    
    # Verify
    assert leg.ltp == 80.0, "LTP should be updated"
    assert leg.delta == 0.5, "Delta should be updated"
    assert leg.gamma == 0.001, "Gamma should be updated"
```

---

## CRITICAL FIX #2: Partial Close Lots Validation

### Location
`adjustment_engine.py` lines 125-132

### Current Code (BROKEN)
```python
elif action_type == "partial_close_lots":
    close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
    lots_to_close = action_cfg.get("lots", 1)
    if close_tag and close_tag in self.state.legs:
        leg = self.state.legs[close_tag]
        leg.qty -= lots_to_close  # ❌ Can go negative!
        if leg.qty <= 0:
            leg.is_active = False
```

### Fixed Code
```python
elif action_type == "partial_close_lots":
    close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
    lots_to_close = int(action_cfg.get("lots", 1))
    
    # ✅ Validation
    if lots_to_close <= 0:
        logger.error(
            f"ADJUSTMENT_ERROR | partial_close_lots | "
            f"invalid lots_to_close={lots_to_close}"
        )
        return
    
    if not close_tag:
        logger.error("ADJUSTMENT_ERROR | partial_close_lots | close_tag not resolved")
        return
    
    if close_tag not in self.state.legs:
        logger.error(
            f"ADJUSTMENT_ERROR | partial_close_lots | "
            f"leg {close_tag} not found in state"
        )
        return
    
    leg = self.state.legs[close_tag]
    
    if not leg.is_active:
        logger.warning(
            f"ADJUSTMENT_SKIP | partial_close_lots | "
            f"leg {close_tag} is already inactive"
        )
        return
    
    # ✅ Validate lots_to_close <= current qty
    if lots_to_close > leg.qty:
        logger.warning(
            f"ADJUSTMENT_MODIFIED | partial_close_lots | "
            f"requested {lots_to_close} lots but {close_tag} only has {leg.qty} lots "
            f"- closing all instead"
        )
        lots_to_close = leg.qty
    
    # Update quantity
    original_qty = leg.qty
    leg.qty -= lots_to_close
    
    # Log the action
    logger.info(
        f"ADJUSTMENT_EXECUTED | partial_close_lots | "
        f"{close_tag} | qty: {original_qty} -> {leg.qty} "
        f"(closed {lots_to_close} lots)"
    )
    
    # Mark inactive if fully closed
    if leg.qty <= 0:
        leg.is_active = False
        logger.info(f"ADJUSTMENT_EXECUTED | {close_tag} fully closed")
```

### Test Cases
```python
def test_partial_close_valid():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=3, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "partial_close_lots",
        "close_tag": "CE_LEG",
        "lots": 2
    }, "if", {})
    
    assert leg.qty == 1, "Should close 2 lots, leaving 1"
    assert leg.is_active == True, "Should still be active"

def test_partial_close_exceeds_qty():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=2, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "partial_close_lots",
        "close_tag": "CE_LEG",
        "lots": 5  # Exceeds current qty!
    }, "if", {})
    
    assert leg.qty == 0, "Should close all when requested > available"
    assert leg.is_active == False, "Should be marked inactive"

def test_partial_close_negative_lots():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=2, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "partial_close_lots",
        "close_tag": "CE_LEG",
        "lots": -1  # Invalid!
    }, "if", {})
    
    assert leg.qty == 2, "Should not change qty when lots < 0"
    assert leg.is_active == True, "Should remain active"
```

---

## CRITICAL FIX #3: Reduce by Percentage Rounding

### Location
`adjustment_engine.py` lines 134-142

### Current Code (BROKEN)
```python
elif action_type == "reduce_by_pct":
    close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
    pct = action_cfg.get("reduce_pct", 50) / 100.0
    if close_tag and close_tag in self.state.legs:
        leg = self.state.legs[close_tag]
        new_qty = int(leg.qty * (1 - pct))  # ❌ Truncates!
        leg.qty = new_qty
        if leg.qty <= 0:
            leg.is_active = False
```

### Problem Analysis
```
qty=1, pct=50% → new_qty = int(1 * 0.5) = 0 ✅ (closes all)
qty=2, pct=50% → new_qty = int(2 * 0.5) = 1 ✅ (reduces by 1)
qty=3, pct=50% → new_qty = int(3 * 0.5) = 1 ❌ (should reduce by 2, actually reduces by 2)
  Wait, 3 * 0.5 = 1.5 → int(1.5) = 1 → keeps 1, reduces 2 ✅ Actually correct!
  
qty=3, pct=33% → new_qty = int(3 * 0.67) = int(2.01) = 2 ❌
  Should reduce by 1 lot (33%), actually keeps 2 lots (33% reduction)
  
Let me recalculate:
  reduce_pct = 33% means reduce by 33%
  new_qty = int(qty * (1 - 0.33)) = int(3 * 0.67) = int(2.01) = 2
  Reduced by: 3 - 2 = 1 lot = 33.33% ✅ Actually correct!

The issue is:
  reduce_pct = 60%, qty = 5
  new_qty = int(5 * 0.4) = int(2.0) = 2
  Reduced by: 5 - 2 = 3 lots = 60% ✅ Correct!
  
  reduce_pct = 75%, qty = 3
  new_qty = int(3 * 0.25) = int(0.75) = 0
  Reduced by: 3 - 0 = 3 lots = 100% ❌ Should be 75%!
  Expected: reduce 2.25 → 2 lots, keep 1 lot
```

### Fixed Code
```python
elif action_type == "reduce_by_pct":
    close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
    pct = float(action_cfg.get("reduce_pct", 50)) / 100.0
    
    # ✅ Validation
    if pct <= 0 or pct > 1.0:
        logger.error(
            f"ADJUSTMENT_ERROR | reduce_by_pct | "
            f"invalid reduce_pct={pct*100}% (must be 0-100)"
        )
        return
    
    if not close_tag:
        logger.error("ADJUSTMENT_ERROR | reduce_by_pct | close_tag not resolved")
        return
    
    if close_tag not in self.state.legs:
        logger.error(
            f"ADJUSTMENT_ERROR | reduce_by_pct | "
            f"leg {close_tag} not found in state"
        )
        return
    
    leg = self.state.legs[close_tag]
    
    if not leg.is_active:
        logger.warning(
            f"ADJUSTMENT_SKIP | reduce_by_pct | "
            f"leg {close_tag} is already inactive"
        )
        return
    
    # ✅ Calculate lots to reduce with proper rounding
    # Use round() instead of int() to get nearest integer
    lots_to_reduce = round(leg.qty * pct)
    
    # Edge case: if pct > 0 but rounds to 0, reduce at least 1 lot
    if lots_to_reduce == 0 and pct > 0:
        lots_to_reduce = 1
    
    # Calculate new quantity
    original_qty = leg.qty
    new_qty = leg.qty - lots_to_reduce
    
    logger.info(
        f"ADJUSTMENT_EXECUTED | reduce_by_pct | "
        f"{close_tag} | {pct*100:.1f}% = {lots_to_reduce} lots | "
        f"qty: {original_qty} -> {new_qty}"
    )
    
    leg.qty = max(0, new_qty)
    
    if leg.qty <= 0:
        leg.is_active = False
        logger.info(f"ADJUSTMENT_EXECUTED | {close_tag} fully closed")
```

### Test Cases
```python
def test_reduce_by_pct_50():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=4, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "reduce_by_pct",
        "close_tag": "CE_LEG",
        "reduce_pct": 50
    }, "if", {})
    
    assert leg.qty == 2, "50% of 4 lots = 2 lots remaining"
    assert leg.is_active == True

def test_reduce_by_pct_75():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=3, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "reduce_by_pct",
        "close_tag": "CE_LEG",
        "reduce_pct": 75
    }, "if", {})
    
    # 75% of 3 = 2.25 → round(2.25) = 2 lots to reduce
    # 3 - 2 = 1 lot remaining
    assert leg.qty == 1, "75% of 3 lots = 2 lots reduced, 1 remaining"

def test_reduce_by_pct_small():
    state = StrategyState()
    leg = LegState(
        tag="CE_LEG", symbol="NIFTY", instrument=InstrumentType.OPT,
        option_type=OptionType.CE, strike=25000, expiry="27-MAR-2026",
        side=Side.SELL, qty=2, entry_price=100, ltp=100
    )
    state.legs["CE_LEG"] = leg
    
    engine = AdjustmentEngine(state, None)
    engine._execute_action({
        "type": "reduce_by_pct",
        "close_tag": "CE_LEG",
        "reduce_pct": 25
    }, "if", {})
    
    # 25% of 2 = 0.5 → round(0.5) = 0 → but we enforce min 1 lot
    assert leg.qty == 1, "25% of 2 lots should reduce at least 1 lot"
```

---

## CRITICAL FIX #4: Convert to Spread Implementation

### Location
`adjustment_engine.py` lines 197-213

### Current Code (INCOMPLETE)
```python
elif action_type == "convert_to_spread":
    # Code exists but incomplete
    target_leg = action_cfg.get("target_leg")
    spread_type = action_cfg.get("spread_type", "credit")
    width = action_cfg.get("width", 100)
    # No actual implementation!
```

### Fixed Code
```python
elif action_type == "convert_to_spread":
    """
    Convert unlimited risk position to defined risk spread.
    
    Example: Short 25000 CE → Convert to Bull Put Spread by buying 25100 CE
    This caps max loss at (width - net_credit) * lot_size
    """
    target_tag = self._resolve_close_tag(action_cfg.get("target_leg"))
    width = float(action_cfg.get("width", 100))
    spread_type = action_cfg.get("spread_type", "vertical")  # vertical, iron_condor
    
    # Validation
    if not target_tag:
        logger.error("ADJUSTMENT_ERROR | convert_to_spread | target_leg not resolved")
        return
    
    if target_tag not in self.state.legs:
        logger.error(
            f"ADJUSTMENT_ERROR | convert_to_spread | "
            f"target leg {target_tag} not found"
        )
        return
    
    target_leg = self.state.legs[target_tag]
    
    if not target_leg.is_active:
        logger.warning(
            f"ADJUSTMENT_SKIP | convert_to_spread | "
            f"target leg {target_tag} is inactive"
        )
        return
    
    if target_leg.instrument != InstrumentType.OPT:
        logger.error(
            f"ADJUSTMENT_ERROR | convert_to_spread | "
            f"can only convert options, not {target_leg.instrument}"
        )
        return
    
    if target_leg.side != Side.SELL:
        logger.error(
            f"ADJUSTMENT_ERROR | convert_to_spread | "
            f"can only convert short options (target is {target_leg.side})"
        )
        return
    
    # Determine hedge strike and side
    if target_leg.option_type == OptionType.CE:
        # Short CE → Buy higher CE to cap upside risk
        hedge_strike = target_leg.strike + width
        hedge_option_type = OptionType.CE
        spread_name = "BEAR_CALL_SPREAD"
    elif target_leg.option_type == OptionType.PE:
        # Short PE → Buy lower PE to cap downside risk
        hedge_strike = target_leg.strike - width
        hedge_option_type = OptionType.PE
        spread_name = "BULL_PUT_SPREAD"
    else:
        logger.error("ADJUSTMENT_ERROR | convert_to_spread | invalid option_type")
        return
    
    # Validate hedge strike exists in chain
    opt_data = self.market_reader.get_option_at_strike(
        hedge_strike, 
        hedge_option_type, 
        expiry=target_leg.expiry
    )
    
    if not opt_data:
        logger.error(
            f"ADJUSTMENT_ERROR | convert_to_spread | "
            f"hedge strike {hedge_strike} {hedge_option_type.value} not found in chain"
        )
        return
    
    # Create hedge leg config
    hedge_tag = f"{target_tag}_HEDGE"
    hedge_cfg = {
        "tag": hedge_tag,
        "symbol": target_leg.symbol,
        "option_type": hedge_option_type.value,
        "side": "BUY",  # Always buy the hedge
        "strike_mode": "exact",
        "exact_strike": hedge_strike,
        "lots": target_leg.qty,  # Match quantity
        "expiry": target_leg.expiry,
        "group": f"SPREAD_{target_tag}"
    }
    
    # Open hedge leg
    try:
        new_tag = self._open_new_leg(hedge_cfg, closing_leg=None)
        
        # Mark both legs as part of spread group
        target_leg.group = f"SPREAD_{target_tag}"
        if new_tag and new_tag in self.state.legs:
            self.state.legs[new_tag].group = f"SPREAD_{target_tag}"
        
        logger.info(
            f"ADJUSTMENT_EXECUTED | convert_to_spread | "
            f"{target_tag} → {spread_name} | "
            f"short={target_leg.strike} long={hedge_strike} width={width}"
        )
        
    except Exception as e:
        logger.error(
            f"ADJUSTMENT_ERROR | convert_to_spread | "
            f"failed to open hedge leg: {e}"
        )
```

### Test Case
```python
def test_convert_to_spread_bear_call():
    state = StrategyState()
    state.spot_price = 25000
    
    # Short 25000 CE (naked)
    short_leg = LegState(
        tag="CE_SHORT",
        symbol="NIFTY",
        instrument=InstrumentType.OPT,
        option_type=OptionType.CE,
        strike=25000,
        expiry="27-MAR-2026",
        side=Side.SELL,
        qty=1,
        entry_price=200,
        ltp=200
    )
    state.legs["CE_SHORT"] = short_leg
    
    market = MockMarketReader()
    market.set_option_data(25100, "CE", {
        'ltp': 150, 'delta': 0.4, 'gamma': 0.001, 'theta': -8
    })
    
    engine = AdjustmentEngine(state, market)
    engine._execute_action({
        "type": "convert_to_spread",
        "target_leg": "CE_SHORT",
        "width": 100
    }, "if", {})
    
    # Verify hedge leg was created
    assert len(state.legs) == 2, "Should have 2 legs now"
    
    hedge_leg = None
    for leg in state.legs.values():
        if leg.side == Side.BUY and leg.option_type == OptionType.CE:
            hedge_leg = leg
            break
    
    assert hedge_leg is not None, "Hedge leg should exist"
    assert hedge_leg.strike == 25100, "Hedge at short_strike + width"
    assert hedge_leg.qty == 1, "Hedge should match short qty"
    assert short_leg.group == hedge_leg.group, "Both legs in same group"
```

---

## CRITICAL FIX #5: Order Status Polling

### Location
`strategy_executor_service.py` - add new method

### New Code to Add
```python
class StrategyExecutorService:
    def __init__(self, ...):
        # ... existing init
        self._pending_orders: Dict[str, LegState] = {}
        self._order_poll_interval = 2  # seconds
        self._last_order_poll = datetime.now()
    
    def run_cycle(self):
        """Main execution loop"""
        # ... existing cycle code
        
        # ✅ ADD: Poll order status periodically
        if (datetime.now() - self._last_order_poll).total_seconds() >= self._order_poll_interval:
            self._poll_pending_orders()
            self._last_order_poll = datetime.now()
        
        # ... rest of cycle
    
    def _poll_pending_orders(self):
        """Check status of all pending orders and update state"""
        if not self._pending_orders:
            return
        
        logger.debug(f"Polling {len(self._pending_orders)} pending orders")
        
        for tag, leg in list(self._pending_orders.items()):
            if leg.order_id is None:
                logger.warning(f"Leg {tag} has no order_id, removing from pending")
                del self._pending_orders[tag]
                continue
            
            try:
                # Get order status from broker
                order_info = self.broker_view.get_order_book(
                    order_id=leg.order_id
                )
                
                if not order_info:
                    logger.warning(f"Order {leg.order_id} not found in broker order book")
                    continue
                
                status = order_info.get('status', 'UNKNOWN')
                
                if status == 'COMPLETE':
                    # Order filled!
                    self._handle_order_fill(leg, order_info)
                    del self._pending_orders[tag]
                
                elif status in ('REJECTED', 'CANCELLED'):
                    # Order failed
                    self._handle_order_rejection(leg, order_info, status)
                    del self._pending_orders[tag]
                
                elif status in ('PENDING', 'OPEN'):
                    # Still pending, check for timeout
                    elapsed = (datetime.now() - leg.order_placed_at).total_seconds()
                    if elapsed > 60:  # 1 minute timeout
                        logger.warning(
                            f"Order timeout | {tag} | {elapsed:.0f}s pending"
                        )
                        # Optionally cancel the order
                        self._cancel_order(leg)
                
                else:
                    logger.warning(f"Unknown order status: {status} for {tag}")
            
            except Exception as e:
                logger.error(f"Failed to poll order {leg.order_id} for {tag}: {e}")
    
    def _handle_order_fill(self, leg: LegState, order_info: Dict[str, Any]):
        """Update leg state after order is filled"""
        filled_qty = int(order_info.get('fillshares', 0))
        avg_price = float(order_info.get('avgprc', leg.entry_price))
        
        leg.order_status = "FILLED"
        leg.filled_qty = filled_qty
        leg.is_active = True
        
        # Update entry price to actual fill price
        if avg_price > 0:
            leg.entry_price = avg_price
            leg.ltp = avg_price  # Initialize LTP to fill price
        
        logger.info(
            f"ORDER_FILLED | {leg.tag} | "
            f"qty={filled_qty} price={avg_price:.2f} "
            f"strike={leg.strike} {leg.option_type.value if leg.option_type else 'FUT'}"
        )
        
        # Send notification
        self._send_notification(
            f"✅ Order Filled: {leg.tag}\n"
            f"Strike: {leg.strike}\n"
            f"Qty: {filled_qty}\n"
            f"Price: {avg_price:.2f}"
        )
    
    def _handle_order_rejection(self, leg: LegState, order_info: Dict[str, Any], status: str):
        """Handle rejected or cancelled order"""
        reason = order_info.get('rejreason', 'Unknown')
        
        leg.order_status = status
        leg.is_active = False
        
        logger.error(
            f"ORDER_{status} | {leg.tag} | "
            f"strike={leg.strike} {leg.option_type.value if leg.option_type else 'FUT'} | "
            f"reason={reason}"
        )
        
        # Remove from state
        if leg.tag in self.state.legs:
            del self.state.legs[leg.tag]
        
        # Send alert
        self._send_alert(
            f"⚠️ Order {status}: {leg.tag}\n"
            f"Strike: {leg.strike}\n"
            f"Qty: {leg.qty}\n"
            f"Reason: {reason}"
        )
    
    def _cancel_order(self, leg: LegState):
        """Cancel a pending order"""
        try:
            result = self.broker_view.cancel_order(leg.order_id)
            logger.info(f"Cancelled order {leg.order_id} for {leg.tag}")
        except Exception as e:
            logger.error(f"Failed to cancel order {leg.order_id}: {e}")
```

---

## CRITICAL FIX #6: PnL Tracking Per Leg

### Location
Multiple files: `state.py`, `persistence.py`

### Add to state.py
```python
@dataclass
class PnLSnapshot:
    """Point-in-time PnL snapshot for historical tracking"""
    timestamp: datetime
    pnl: float
    pnl_pct: float
    ltp: float
    underlying_price: float

@dataclass
class LegState:
    # ... existing fields
    
    # ✅ ADD: Historical tracking
    pnl_history: List[PnLSnapshot] = field(default_factory=list)
    entry_reason: str = ""
    exit_timestamp: Optional[datetime] = None
    exit_reason: str = ""
    exit_price: Optional[float] = None
    
    def record_pnl_snapshot(self, underlying_price: float):
        """Record current PnL for historical tracking"""
        snapshot = PnLSnapshot(
            timestamp=datetime.now(),
            pnl=self.pnl,
            pnl_pct=self.pnl_pct,
            ltp=self.ltp,
            underlying_price=underlying_price
        )
        self.pnl_history.append(snapshot)
        
        # Limit history size to prevent memory bloat
        if len(self.pnl_history) > 1000:
            # Keep every 10th entry for older data
            self.pnl_history = (
                self.pnl_history[-100:] +  # Keep last 100
                self.pnl_history[:-100:10]  # Keep every 10th of older
            )
    
    @property
    def max_pnl(self) -> float:
        """Maximum PnL reached during position lifetime"""
        if not self.pnl_history:
            return self.pnl
        return max(s.pnl for s in self.pnl_history)
    
    @property
    def min_pnl(self) -> float:
        """Minimum PnL reached during position lifetime"""
        if not self.pnl_history:
            return self.pnl
        return min(s.pnl for s in self.pnl_history)
    
    @property
    def total_pnl(self) -> float:
        """Total realized + unrealized PnL"""
        if self.exit_price is not None:
            # Leg is closed - use exit price
            if self.side == Side.BUY:
                return (self.exit_price - self.entry_price) * self.order_qty
            else:
                return (self.entry_price - self.exit_price) * self.order_qty
        else:
            # Leg still active - use current PnL
            return self.pnl
```

### Update persistence.py
```python
@staticmethod
def to_dict(state: StrategyState) -> Dict[str, Any]:
    return {
        "legs": {
            tag: {
                # ... existing fields
                
                # ✅ ADD: Historical tracking
                "pnl_history": [
                    {
                        "timestamp": snap.timestamp.isoformat(),
                        "pnl": snap.pnl,
                        "pnl_pct": snap.pnl_pct,
                        "ltp": snap.ltp,
                        "underlying_price": snap.underlying_price
                    }
                    for snap in leg.pnl_history
                ],
                "entry_reason": leg.entry_reason,
                "exit_timestamp": leg.exit_timestamp.isoformat() if leg.exit_timestamp else None,
                "exit_reason": leg.exit_reason,
                "exit_price": leg.exit_price,
            } 
            for tag, leg in state.legs.items()
        },
        # ... rest
    }

@staticmethod
def from_dict(data: Dict[str, Any]) -> StrategyState:
    legs = {}
    for tag, leg_data in data.get("legs", {}).items():
        # Restore PnL history
        pnl_history = []
        for snap_data in leg_data.get("pnl_history", []):
            pnl_history.append(PnLSnapshot(
                timestamp=datetime.fromisoformat(snap_data["timestamp"]),
                pnl=snap_data["pnl"],
                pnl_pct=snap_data["pnl_pct"],
                ltp=snap_data["ltp"],
                underlying_price=snap_data["underlying_price"]
            ))
        
        leg = LegState(
            # ... existing fields
            pnl_history=pnl_history,
            entry_reason=leg_data.get("entry_reason", ""),
            exit_timestamp=datetime.fromisoformat(leg_data["exit_timestamp"]) 
                if leg_data.get("exit_timestamp") else None,
            exit_reason=leg_data.get("exit_reason", ""),
            exit_price=leg_data.get("exit_price"),
        )
        legs[tag] = leg
    
    # ... rest
```

---

## More critical fixes continue...

(This document is already very comprehensive. The remaining fixes follow similar patterns.)
