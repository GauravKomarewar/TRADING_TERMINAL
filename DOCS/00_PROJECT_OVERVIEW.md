# Shoonya Trading Platform — Project Overview

> Last verified: 2026-03-01 | Python 3.12.3 | 89 source files across 15 packages

## Architecture Summary

Single-process trading platform for Shoonya (Finvasia) broker. Two HTTP servers run concurrently:

| Service | Framework | Default Port | Binding | Purpose |
|---------|-----------|-------------|---------|---------|
| Execution Service | Flask + Waitress | `5000` (env: `PORT`) | `0.0.0.0` | Webhook alerts, Telegram commands |
| Dashboard | FastAPI + uvicorn | `8000` (env: `DASHBOARD_PORT`) | `127.0.0.1` | Web UI, strategy management, monitoring |

**Entry Point:** `main.py` → creates `ShoonyaBot(config)` → starts both servers.

---

## System Data Flow

```
TradingView/Webhook ──► ExecutionApp (Flask:5000) ──► ShoonyaBot.process_alert()
                                                           │
Dashboard (FastAPI:8000) ──► Intent Queues ──► GenericControlIntentConsumer
                                            ──► StrategyControlConsumer
                                                           │
                                                    ┌──────┴──────┐
                                                    ▼              ▼
                                             CommandService   StrategyExecutorService
                                                    │              │
                                                    ▼              ▼
                                             OrderWatcherEngine   PerStrategyExecutor
                                                    │              │
                                                    ▼              ▼
                                                 Broker ──► Shoonya API
                                                    │
                                                    ▼
                                             OrderRepository (SQLite)
```

---

## Package Map

```
shoonya_platform/
├── analytics/                    # Historical trade analytics (PostgreSQL-backed)
│   ├── historical_service.py     #   HistoricalAnalyticsService - API layer
│   └── historical_store.py       #   HistoricalStore - data persistence
│
├── api/
│   ├── dashboard/                # FastAPI dashboard (port 8000)
│   │   ├── auth.py               #   Cookie-based session auth (DASHBOARD_PASSWORD)
│   │   ├── dashboard_app.py      #   create_dashboard_app() factory
│   │   ├── deps.py               #   Dependency injection (auth middleware)
│   │   ├── api/
│   │   │   ├── router.py         #   Master API router (4081 lines, 97 handlers, 70 routes)
│   │   │   └── schemas.py        #   Pydantic request/response schemas
│   │   ├── services/
│   │   │   ├── broker_service.py #   Broker operations facade
│   │   │   ├── intent_utility.py #   Intent construction helpers
│   │   │   ├── option_chain_service.py
│   │   │   ├── supervisor_service.py  # Option chain supervisor
│   │   │   ├── symbols_utility.py     # Symbol/expiry lookups
│   │   │   └── system_service.py      # System health/stats
│   │   └── web/                  #   10 HTML pages (see Dashboard doc)
│   │
│   └── http/                     # Flask execution service (port 5000)
│       ├── execution_app.py      #   ExecutionApp - webhook + alert processing
│       └── telegram_controller.py #  Telegram bot command handler
│
├── brokers/
│   └── shoonya/
│       └── client.py             # ShoonyaClient - raw API wrapper (1866 lines)
│
├── core/
│   └── config.py                 # Config class - loads from .env (626 lines)
│
├── domain/
│   ├── business_models.py        # AlertData, BotStats, PositionInfo
│   └── models.py                 # Legacy compatibility shim
│
├── execution/                    # Core execution engine (13 modules)
│   ├── trading_bot.py            # ShoonyaBot - central orchestrator (2645 lines)
│   ├── command_service.py        # CommandService - order placement & modification
│   ├── order_watcher.py          # OrderWatcherEngine - fill monitoring thread
│   ├── execution_guard.py        # ExecutionGuard - position/fill validation
│   ├── broker.py                 # Broker - abstraction over ShoonyaClient
│   ├── intent.py                 # UniversalOrderCommand - intent data model
│   ├── intent_tracker.py         # IntentTracker - tracks intent lifecycle
│   ├── generic_control_consumer.py    # Dashboard generic intent consumer
│   ├── strategy_control_consumer.py   # Dashboard strategy intent consumer
│   ├── position_exit_service.py  # Batch position exit logic
│   ├── recovery.py               # Order recovery utilities
│   ├── strategy_intent.py        # Strategy-specific intent models
│   ├── trailing.py               # Trailing stop-loss logic
│   └── validation.py             # Pre-trade validation rules
│
├── logging/
│   └── logger_config.py          # setup_application_logging() - per-client log dirs
│
├── market_data/
│   ├── feeds/
│   │   ├── live_feed.py          # LiveFeed - WebSocket tick data
│   │   └── index_tokens_subscriber.py  # IndexTokensSubscriber
│   ├── instruments/
│   │   └── instruments.py        # Instrument resolution
│   └── option_chain/
│       ├── option_chain.py       # Option chain data model
│       ├── db_access.py          # ScriptMaster DB queries
│       ├── store.py              # In-memory option chain store
│       ├── supervisor.py         # Option chain refresh supervisor
│       └── supervisor_monitor.py # Supervisor health monitoring
│
├── persistence/                  # SQLite persistence layer
│   ├── database.py               # get_connection() - centralized WAL-mode DB
│   ├── repository.py             # OrderRepository - CRUD for orders/positions
│   ├── order_record.py           # OrderRecord dataclass
│   ├── models.py                 # Compatibility shim → order_record
│   └── audit_strategy.py         # Strategy audit trail
│
├── risk/
│   └── supreme_risk.py           # SupremeRiskManager - PnL tracking & kill switch
│
├── services/
│   ├── service_manager.py        # ServiceManager - lifecycle coordinator
│   ├── recovery_service.py       # RecoveryBootstrap - startup reconciliation
│   └── orphan_position_manager.py # Orphan position detection & rules
│
├── strategy_runner/              # Strategy execution engine
│   ├── executor.py               # StrategyExecutor - main entry point
│   ├── strategy_executor_service.py  # StrategyExecutorService (1785 lines)
│   ├── config_schema.py          # validate_config() - JSON schema validator (1345 lines)
│   ├── entry_engine.py           # EntryEngine - trade entry logic
│   ├── exit_engine.py            # ExitEngine - trade exit logic
│   ├── adjustment_engine.py      # AdjustmentEngine - position adjustments
│   ├── condition_engine.py       # ConditionEngine - condition evaluation
│   ├── market_reader.py          # MarketReader - market data for strategies
│   ├── state.py                  # StrategyState, LegState
│   ├── models.py                 # Condition, StrikeConfig, enums
│   ├── persistence.py            # Strategy state persistence
│   ├── reconciliation.py         # BrokerReconciliation
│   ├── simulation_harness.py     # Backtesting harness
│   ├── universal_settings/
│   │   ├── universal_registry.py     # list_strategy_templates()
│   │   ├── universal_strategy_reporter.py  # build_strategy_report()
│   │   └── writer.py                 # StrategyRunWriter
│   └── saved_configs/            # JSON strategy configs
│       ├── nifty_dnss_actual.json
│       ├── crudeoilm_dnss_actual.json
│       ├── crudeoilm_test_all.json
│       └── strategy_config.schema.json
│
├── tools/                        # Developer utilities
│   ├── broker_inspect.py         # Broker state inspection
│   ├── cleanup.py                # Database/log cleanup
│   ├── test_place_order.py       # Manual order placement test
│   └── test_webhook.py           # Webhook simulation test
│
└── utils/
    ├── bs_greeks.py              # Black-Scholes Greeks calculator
    ├── json_builder.py           # JSON alert builder
    ├── text_sanitize.py          # Text sanitization
    └── utils.py                  # General utilities
```

---

## Supporting Directories

| Directory | Contents |
|-----------|----------|
| `config_env/` | `primary.env`, `primary.env.example`, `sample.env` |
| `deployment/` | `trading.service`, `install_schedulers.sh`, `deploy_improvements.sh`, systemd timers |
| `scripts/` | `scriptmaster.py`, `verify_orders.py`, `weekend_market_check.py`, `run_scalper_debug.py`, `generate_api_reference.py` |
| `tests/` | 35 test files, 336 passing tests |
| `notifications/` | `telegram.py` — Telegram notification sender |
| `utilities/` | `bootstrap.sh`, `full_system.sh`, operational scripts |
| `requirements/` | `NorenRestApi-0.0.30-py2.py3-none-any.whl` |
| `logs/` | Per-client log directories (auto-created) |

---

## Key Design Principles

1. **Intent-Based OMS**: Dashboard never touches broker directly. It queues intents → consumers process them.
2. **Single Source of Truth**: `OrderRepository` (SQLite WAL mode) is the canonical order store.
3. **Strategy Runner Only**: All strategy logic lives in `strategy_runner/`. No other strategy engine exists.
4. **Per-Rule Cooldowns**: Adjustment engine tracks cooldown per rule name, not globally.
5. **Centralized DB Access**: All modules use `get_connection()` from `persistence/database.py` — never raw `sqlite3.connect()`.
6. **Graceful Shutdown**: SIGTERM → 30s timeout → coordinated thread shutdown.
