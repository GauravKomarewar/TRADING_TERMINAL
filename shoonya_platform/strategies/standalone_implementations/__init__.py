"""
Standalone Strategy Implementations
====================================

This folder contains independent strategy implementations that support:

1. **Dashboard Integration**: Register with StrategyRunner via UniversalStrategyConfig
2. **Standalone CLI**: Run strategies directly from command-line with JSON configs  
3. **System Integration**: Use as reference implementations for new strategies

## Structure

Each strategy folder (e.g., `delta_neutral/`) contains:
- `strategy_name.py`: Core strategy logic
- `adapter.py`: Bridge to UniversalStrategyConfig (unified runner)
- `__init__.py`: Clean exports

## How to Add a New Strategy

1. Create `new_strategy/` folder with same structure:
   ```
   new_strategy/
   ├── new_strategy.py  (core logic)
   ├── adapter.py       (UniversalStrategyConfig bridge)
   └── __init__.py      (exports)
   ```

2. Implement adapter functions to convert between:
   - Strategy-specific config → UniversalStrategyConfig (for dashboard)
   - UniversalStrategyConfig → Strategy-specific config (for runner)

3. Import in main strategies __init__.py if needed for system-wide access

## Current Strategies

- **delta_neutral/**: Delta Neutral Short Strangle (DNSS)
  - Production-grade with atomic adjustments
  - Full recovery support via state persistence
  - Broker position resilience

## Integration Paths

### Path 1: Dashboard → StrategyRunner (Modern Recommended)
1. User creates config in dashboard
2. Dashboard stores UniversalStrategyConfig in DB
3. StrategyRunner loads config
4. Adapter converts to strategy-specific config
5. Strategy runs against unified OMS

### Path 2: Standalone CLI (Legacy Reference)
1. User provides JSON config file
2. Strategy loads natively without adapter
3. Strategy emits UniversalOrderCommand intents
4. Process alert executor handles OMS integration

### Path 3: Direct Python Integration
1. Import adapter functions directly
2. Build strategy from config manually
3. Integrate with custom execution system
"""

__all__ = []
