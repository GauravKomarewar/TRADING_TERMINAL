# Testing Guide

> Last verified: 2026-03-01 | 336 tests passing | Python 3.12.3

## Running Tests

```bash
cd /home/ubuntu/shoonya_platform
source venv/bin/activate

# Full suite
python3 -m pytest tests/ -q

# With verbose output
python3 -m pytest tests/ -v

# Single test file
python3 -m pytest tests/test_condition_engine.py -v

# Single test
python3 -m pytest tests/test_adjustment_guards.py::test_cooldown -v

# Stop on first failure
python3 -m pytest tests/ -x

# With coverage (if pytest-cov installed)
python3 -m pytest tests/ --cov=shoonya_platform --cov-report=term-missing
```

---

## Test Files

| File | Tests | Covers |
|------|-------|--------|
| `test_adjustment_guards.py` | Adjustment engine cooldowns, guards, per-rule tracking |
| `test_api_proxy.py` | ShoonyaApiProxy wrapper methods |
| `test_command_service.py` | Order placement, modification, cancellation |
| `test_condition_engine.py` | Condition evaluation (comparators, AND/OR, parameters) |
| `test_critical_components.py` | Integration: config → bot → command chain |
| `test_entry_paths_complete.py` | All entry paths (webhook, dashboard, strategy) |
| `test_exit_paths_complete.py` | All exit paths (SL, TP, EOD, trailing, force) |
| `test_hardening_critical_paths.py` | No bare excepts, cooldown uses injected time, test mode |
| `test_index_condition_params.py` | Index token parameters (VIX, etc.) in conditions |
| `test_integration_edge_cases.py` | Edge cases: empty configs, malformed data, timeouts |
| `test_integration_system.py` | End-to-end: registry, validation, reporter, writer |
| `test_market_adapter_factory.py` | Market adapter resolution |
| `test_multi_client.py` | Multi-client isolation |
| `test_new_modules.py` | Smoke tests for migrated strategy_runner modules |
| `test_option_chain_nearest.py` | Nearest option finding logic |
| `test_order_watcher.py` | Fill monitoring, timeout handling, partial fills |
| `test_reconciliation.py` | Broker position reconciliation |
| `test_repository.py` | OrderRepository CRUD, SQLite operations |
| `test_restart_recovery.py` | Bot restart and strategy recovery |
| `test_risk_and_validation.py` | Risk manager + pre-trade validation |
| `test_risk_manager.py` | SupremeRiskManager PnL tracking, kill switch |
| `test_strategy_executor_service_critical.py` | StrategyExecutorService lifecycle |
| `test_strategy_hardening_regression.py` | Regression tests for strategy edge cases |
| `test_strategy_registry.py` | Strategy template registry |
| `test_strategy_reporter.py` | Strategy report generation |
| `test_strategy_runner.py` | StrategyExecutor core logic |
| `test_strategy_writer.py` | StrategyRunWriter persistence |
| `test_strike_selection.py` | Strike resolution (ATM, OTM, exact, etc.) |

### Support Files

| File | Purpose |
|------|---------|
| `conftest.py` | Shared fixtures (mock broker, test configs) |
| `conftest_comprehensive.py` | Extended fixtures for integration tests |
| `fake_broker.py` | Mock broker implementation for testing |
| `live_feed_stress_test.py` | WebSocket load testing (manual run) |
| `test.py`, `test2.py` | Ad-hoc manual test scripts |

---

## Test Architecture

Tests use `unittest.mock` for isolation:

```python
# Example: testing command service without real broker
from unittest.mock import Mock, patch
from shoonya_platform.execution.command_service import CommandService

def test_order_placement():
    mock_broker = Mock()
    mock_broker.place_order.return_value = {"norenordno": "12345"}
    
    service = CommandService(broker=mock_broker, repository=Mock())
    result = service.execute(order_command)
    
    mock_broker.place_order.assert_called_once()
```

Key testing patterns:
- **No real broker calls** — all tests use mock broker
- **In-memory SQLite** — tests create temporary databases
- **Isolated state** — each test gets fresh `StrategyState`
- **Condition engine** — tested with synthetic market data

---

## Adding New Tests

1. Create test file in `tests/` with `test_` prefix
2. Import the module under test
3. Use fixtures from `conftest.py` for common setup
4. Follow existing patterns for mock construction

```python
# tests/test_my_feature.py
import pytest
from unittest.mock import Mock
from shoonya_platform.strategy_runner.my_module import MyClass

def test_my_feature():
    obj = MyClass(mock_dependency=Mock())
    result = obj.do_something()
    assert result == expected_value
```

---

## Quick Validation

After any code change, run:

```bash
# Syntax check all files
python3 -c "
import ast, pathlib
for p in pathlib.Path('shoonya_platform').rglob('*.py'):
    try: ast.parse(p.read_text())
    except SyntaxError as e: print(f'SYNTAX ERROR: {p}: {e}')
print('AST parse complete')
"

# Import smoke test
DASHBOARD_PASSWORD=test python3 -c "
from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.execution.command_service import CommandService
from shoonya_platform.strategy_runner.executor import StrategyExecutor
from shoonya_platform.strategy_runner.config_schema import validate_config
from shoonya_platform.persistence.database import get_connection
print('All critical imports OK')
"

# Full test suite
python3 -m pytest tests/ -q --tb=short
```
