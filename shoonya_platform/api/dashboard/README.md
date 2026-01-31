Dashboard — Strategy Registration & Supervisor
=============================================

Purpose
-------
This document explains how to register strategy instances with the running `ShoonyaBot` so that the Dashboard control-plane (buttons: ENTRY / EXIT / ADJUST / FORCE_EXIT) can control strategy lifecycle.

Key concepts
------------
- The Dashboard is intent-only: it writes control intents to `control_intents` table.
- Execution-side consumers pick up STRATEGY intents and call lifecycle methods on the strategy manager (the running `ShoonyaBot`).
- For dashboard-to-engine direct lifecycle control, the `ShoonyaBot` exposes the following methods which are invoked by `StrategyControlConsumer`:
  - `request_entry(strategy_name)`
  - `request_exit(strategy_name)`
  - `request_adjust(strategy_name)`
  - `request_force_exit(strategy_name)`

Registering a live strategy
---------------------------
A running strategy should call `register_live_strategy()` on the bot to allow dashboard/consumers to route lifecycle commands to it.

Example (inside strategy runner):

```python
from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.strategies.delta_neutral.delta_neutral_short_strategy import DeltaNeutralShortStrangleStrategy

bot = ShoonyaBot()

strategy = DeltaNeutralShortStrangleStrategy(...)
# market is the LiveMarket or DBBackedMarket instance used by Engine
bot.register_live_strategy("NIFTY_DELTA_AUTO_ADJUST", strategy, market)
```

What registration enables
------------------------
- `StrategyControlConsumer` claims STRATEGY intents (created by dashboard) and invokes `bot.request_entry/exit/adjust/force_exit(strategy_name)`.
- When registered, the bot will call into the strategy's hooks (`on_tick`, `force_exit`, `prepare`) and convert `Intent` objects returned into canonical `UniversalOrderCommand`s which are persisted/executed via `CommandService`.

Supervisor endpoints (optional)
-------------------------------
A lightweight supervisor is provided to allow starting/stopping strategy runners from the dashboard (protected endpoints). The supervisor launches the strategy runner as a subprocess and tracks PID files in the system temp directory. Use with caution — starting strategies requires the same runtime environment and credentials as starting from CLI.

Security
--------
- Dashboard endpoints are authenticated via `require_dashboard_auth` (cookie-based operator auth).
- Starting/stopping strategies requires OS-level permission to spawn/kill processes; ensure the dashboard host has appropriate privileges.

Notes
-----
- The dashboard codebase uses production-safe default paths for option-chain DB and persistence; when running locally, ensure the paths in environment and config are adjusted or symlinked.
- Registering strategies is read-only registration for reporting and lifecycle control; it does not change strategy behavior.

