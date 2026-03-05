# IMPLEMENTATION ROADMAP
## Shoonya Trading Platform - Bug Fix & Enhancement Plan

**Prepared:** March 5, 2026  
**Status:** Ready for Implementation  
**Estimated Timeline:** 4-6 weeks for critical path

---

## PHASE 1: CRITICAL STABILITY FIXES (Week 1)
**Goal:** Make system production-stable
**Success Criteria:** No data loss, accurate trade execution

### Day 1-2: Market Data & Greeks Refresh
**Priority:** P0 - CRITICAL  
**Effort:** 8 hours  
**Risk:** HIGH - Affects all adjustment decisions

**Tasks:**
1. [ ] Implement `_refresh_leg_market_data()` in strategy_executor_service.py
2. [ ] Add market data refresh to main execution loop
3. [ ] Test with live market data
4. [ ] Verify Greeks update correctly
5. [ ] Add logging for stale data detection

**Files Modified:**
- `strategy_runner/strategy_executor_service.py`

**Test Cases:**
- Entry with delta 0.3, spot moves, verify delta updates to 0.5
- Multiple legs, verify all update
- One leg has missing data, verify others still update

---

### Day 2-3: Order Status Polling
**Priority:** P0 - CRITICAL  
**Effort:** 12 hours  
**Risk:** HIGH - Orders may never fill

**Tasks:**
1. [ ] Add `_pending_orders` tracking dict
2. [ ] Implement `_poll_pending_orders()` method
3. [ ] Handle FILLED, REJECTED, CANCELLED status
4. [ ] Add order timeout logic (60s default)
5. [ ] Implement notifications on fill/reject
6. [ ] Test with broker simulator

**Files Modified:**
- `strategy_runner/strategy_executor_service.py`

**Test Cases:**
- Order fills immediately
- Order fills after 10 seconds
- Order rejected (insufficient margin)
- Order times out

---

### Day 3-4: Adjustment Validation Fixes
**Priority:** P0 - CRITICAL  
**Effort:** 6 hours  
**Risk:** MEDIUM - Can cause invalid positions

**Tasks:**
1. [ ] Fix partial_close_lots validation (BUG-008)
2. [ ] Fix reduce_by_pct rounding (BUG-009)
3. [ ] Add comprehensive validation for all adjustment actions
4. [ ] Add unit tests for edge cases

**Files Modified:**
- `strategy_runner/adjustment_engine.py`

**Test Cases:**
- Partial close more than available qty
- Reduce by 75% of 3 lots
- Partial close with negative lots
- Reduce by 0% (should do nothing)
- Reduce by 100% (should close all)

---

### Day 4-5: PnL Tracking & Persistence
**Priority:** P0 - CRITICAL  
**Effort:** 10 hours  
**Risk:** MEDIUM - Affects reporting

**Tasks:**
1. [ ] Add PnLSnapshot dataclass to state.py
2. [ ] Implement pnl_history tracking in LegState
3. [ ] Add entry_reason, exit_reason fields
4. [ ] Update persistence.py to save/load history
5. [ ] Add `record_pnl_snapshot()` calls in main loop
6. [ ] Implement PnL charting API endpoint

**Files Modified:**
- `strategy_runner/state.py`
- `strategy_runner/persistence.py`
- `api/dashboard/api/routes_monitoring.py`

**Test Cases:**
- Record 100 PnL snapshots
- Verify history saved to disk
- Restart system, verify history restored
- Test max_pnl, min_pnl properties

---

## PHASE 2: HIGH PRIORITY FEATURES (Week 2)

### Day 6-7: Broker Reconciliation Enhancement
**Priority:** P1 - HIGH  
**Effort:** 8 hours  
**Risk:** MEDIUM - Manual interventions can break strategy

**Tasks:**
1. [ ] Add LTP update from broker quotes
2. [ ] Add side verification
3. [ ] Handle partial position liquidations
4. [ ] Add average entry price sync
5. [ ] Improve empty position handling

**Files Modified:**
- `strategy_runner/reconciliation.py`

**Test Cases:**
- Manual exit of 1 leg out of 2
- Broker session failure (empty positions)
- Manual quantity reduction
- Manual flip from SELL to BUY

---

### Day 7-8: Convert to Spread Implementation
**Priority:** P1 - HIGH  
**Effort:** 6 hours  
**Risk:** LOW - New feature

**Tasks:**
1. [ ] Implement convert_to_spread action
2. [ ] Add hedge leg creation logic
3. [ ] Link legs to spread group
4. [ ] Test bear call spread
5. [ ] Test bull put spread

**Files Modified:**
- `strategy_runner/adjustment_engine.py`

**Test Cases:**
- Short 25000 CE → Convert to bear call spread
- Short 24800 PE → Convert to bull put spread
- Convert with width=100, 200, 500
- Hedge strike doesn't exist in chain (error handling)

---

### Day 8-9: Roll to Next Expiry Fixes
**Priority:** P1 - HIGH  
**Effort:** 4 hours  
**Risk:** MEDIUM - Calendar spreads broken

**Tasks:**
1. [ ] Fix strike step validation
2. [ ] Add rounding to nearest valid strike
3. [ ] Validate new expiry chain has required strikes
4. [ ] Test weekly→monthly roll
5. [ ] Test monthly→weekly roll

**Files Modified:**
- `strategy_runner/adjustment_engine.py`
- `strategy_runner/market_reader.py`

**Test Cases:**
- Roll 24850 weekly to monthly (step changes 50→100)
- Roll with same_strike="atm"
- Roll with same_strike="yes" but strike missing in new expiry

---

### Day 9-10: Entry Guards & Limits
**Priority:** P1 - HIGH  
**Effort:** 4 hours  
**Risk:** LOW - Safety feature

**Tasks:**
1. [ ] Add max_entries_per_day guard
2. [ ] Add entry_cooldown_sec guard
3. [ ] Add max_total_entries guard
4. [ ] Test with strategy that re-enters

**Files Modified:**
- `strategy_runner/entry_engine.py`

**Test Cases:**
- max_entries_per_day=1, try to enter twice
- entry_cooldown_sec=300, try to re-enter after 100s
- Verify guards reset at day rollover

---

## PHASE 3: MEDIUM PRIORITY ENHANCEMENTS (Week 3)

### Day 11-12: Structured Event Logging
**Priority:** P2 - MEDIUM  
**Effort:** 10 hours  
**Risk:** LOW - Infrastructure improvement

**Tasks:**
1. [ ] Create StrategyEvent dataclass
2. [ ] Implement EventLogger class
3. [ ] Add event storage table
4. [ ] Integrate logging in entry/adjustment/exit
5. [ ] Create API endpoints for event query

**Files Modified:**
- `strategy_runner/models.py` (add StrategyEvent)
- `strategy_runner/strategy_executor_service.py`
- `api/dashboard/api/routes_monitoring.py`

**Deliverable:**
- Dashboard page showing strategy timeline
- Each event has timestamp, type, reason, affected legs
- Filter by event type, date range

---

### Day 12-13: Risk Limits Framework
**Priority:** P2 - MEDIUM  
**Effort:** 8 hours  
**Risk:** MEDIUM - Safety critical

**Tasks:**
1. [ ] Create RiskLimits dataclass
2. [ ] Implement RiskManager class
3. [ ] Add limit checks before entry/adjustment
4. [ ] Add circuit breaker on limit violation
5. [ ] Add notifications on approaching limits

**Files Modified:**
- `strategy_runner/models.py`
- `strategy_runner/strategy_executor_service.py`

**Limits to Implement:**
- Max margin usage %
- Max net delta
- Max loss per day
- Max position value
- Max Greeks exposure

---

### Day 13-14: Trailing Stop Enhancement
**Priority:** P2 - MEDIUM  
**Effort:** 6 hours  
**Risk:** LOW - Feature improvement

**Tasks:**
1. [ ] Add percentage-based trailing stop
2. [ ] Fix realized PnL inclusion
3. [ ] Add step trigger validation
4. [ ] Test continuous vs step-based trailing

**Files Modified:**
- `strategy_runner/exit_engine.py`

**Test Cases:**
- Trailing by $100 from peak
- Trailing by 10% from peak
- Step trigger every $50 gain
- Realized PnL included in calculations

---

### Day 14-15: Index Data Refresh
**Priority:** P2 - MEDIUM  
**Effort:** 4 hours  
**Risk:** LOW - Nice to have

**Tasks:**
1. [ ] Add index ticker subscription
2. [ ] Refresh state.index_data in main loop
3. [ ] Test index_NIFTY_change_pct conditions

**Files Modified:**
- `strategy_runner/strategy_executor_service.py`

---

## PHASE 4: TESTING & VALIDATION (Week 4)

### Day 16-18: Comprehensive Test Suite
**Effort:** 20 hours

**Tasks:**
1. [ ] Unit tests for all engines
2. [ ] Integration tests for full lifecycle
3. [ ] Edge case testing
4. [ ] Performance testing
5. [ ] Stress testing (1000 cycles)

**Test Coverage Target:** 80%+

**Critical Test Scenarios:**
- Strategy enters, makes 5 adjustments, exits with profit
- Strategy enters, stop loss triggers immediately
- Strategy enters, system crashes, restarts, resumes
- Manual exit of one leg detected and handled
- Broker rejects order, strategy adapts
- Market data goes stale, strategy pauses
- Multiple strategies running simultaneously

---

### Day 18-20: Backtesting Framework
**Effort:** 16 hours

**Tasks:**
1. [ ] Create MockMarketReader with replay capability
2. [ ] Implement historical data loader
3. [ ] Add fill simulation with slippage
4. [ ] Create performance report generator
5. [ ] Test with NIFTY data from Jan-Dec 2025

**Deliverable:**
- Backtest any strategy JSON
- Output: Sharpe ratio, max DD, win rate, etc.
- Compare multiple configurations side-by-side

---

## PHASE 5: PRODUCTION HARDENING (Week 5-6)

### Week 5: Monitoring & Alerting
**Tasks:**
1. [ ] Set up application logging to ELK/Splunk
2. [ ] Configure alerts for critical errors
3. [ ] Add health check endpoints
4. [ ] Implement dead man's switch
5. [ ] Add performance metrics (latency, throughput)

---

### Week 6: Documentation & Training
**Tasks:**
1. [ ] Update API documentation
2. [ ] Create user guide for strategy builder
3. [ ] Document all adjustment types
4. [ ] Create troubleshooting guide
5. [ ] Record training videos

---

## SUCCESS METRICS

### Code Quality
- [ ] 0 critical bugs remaining
- [ ] 80%+ test coverage
- [ ] All linting rules pass
- [ ] Type hints on all functions

### Functional
- [ ] Entry success rate: 95%+
- [ ] Adjustment execution rate: 99%+
- [ ] Exit execution rate: 100%
- [ ] Order fill rate: 95%+
- [ ] Reconciliation accuracy: 100%

### Performance
- [ ] Cycle time: <1 second
- [ ] Market data refresh: <500ms
- [ ] State persistence: <100ms
- [ ] Crash recovery: <10 seconds

### Reliability
- [ ] Uptime: 99.9%+
- [ ] Data loss: 0%
- [ ] Missed exits: 0%
- [ ] False reconciliation alerts: <1%

---

## ROLLOUT PLAN

### Stage 1: Internal Testing (Week 4)
- Deploy to development environment
- Run with paper trading account
- Monitor for 5 consecutive days
- Fix any issues found

### Stage 2: Beta Testing (Week 5)
- Deploy to staging environment
- Invite 3-5 beta testers
- Monitor with real money, small position sizes
- Collect feedback

### Stage 3: Production (Week 6)
- Deploy to production
- Enable for all users
- Monitor closely for first week
- Have rollback plan ready

---

## RISK MITIGATION

### Technical Risks
| Risk | Mitigation |
|------|-----------|
| Market data feed fails | Cache last known data, alert user |
| Broker API timeout | Retry with exponential backoff |
| State corruption | Atomic writes, backups every 5 min |
| Out of memory | Limit history size, GC tuning |

### Business Risks
| Risk | Mitigation |
|------|-----------|
| User loses money due to bug | Insurance fund, bug bounty program |
| Regulatory compliance | Audit trail, position limits |
| System abuse | Rate limiting, API keys |
| Competition | Patents, trade secrets |

---

## RESOURCE ALLOCATION

### Team Required
- 1 Senior Python Developer (full-time, 6 weeks)
- 1 QA Engineer (full-time, weeks 4-6)
- 1 DevOps Engineer (part-time, weeks 5-6)
- 1 Technical Writer (part-time, week 6)

### Budget Estimate
- Development: 6 weeks × $5K/week = $30K
- Testing: 2 weeks × $3K/week = $6K
- Infrastructure: $2K
- **Total: $38K**

---

## DEPENDENCIES

### External
- Broker API stability
- Market data feed reliability
- Python 3.12+ environment
- SQLite 3.35+

### Internal
- strategy_builder.html (frontend) updates
- option chain DB writer running
- Telegram notification service

---

## MONITORING CHECKLIST

Post-deployment, monitor these metrics daily:

**System Health:**
- [ ] CPU usage < 70%
- [ ] Memory usage < 80%
- [ ] Disk usage < 90%
- [ ] No error spikes in logs

**Strategy Execution:**
- [ ] Entry success rate
- [ ] Adjustment execution rate
- [ ] Exit completion rate
- [ ] Average cycle time

**Data Quality:**
- [ ] Market data freshness
- [ ] State persistence success
- [ ] Reconciliation warnings
- [ ] Order fill rate

**User Experience:**
- [ ] Dashboard load time < 2s
- [ ] API response time < 500ms
- [ ] No user complaints
- [ ] Support ticket count

---

## CONCLUSION

This roadmap prioritizes:
1. **Safety first** - Fix critical bugs that could cause incorrect trades
2. **Stability** - Ensure system can run 24/7 without intervention
3. **Observability** - Add logging and monitoring for debugging
4. **Performance** - Optimize after functionality is correct

Following this plan, the trading platform will be production-ready in 6 weeks with:
- All critical bugs fixed
- Comprehensive test coverage
- Production monitoring in place
- User documentation complete

**Ready to begin Phase 1? Let's fix those critical bugs!**
