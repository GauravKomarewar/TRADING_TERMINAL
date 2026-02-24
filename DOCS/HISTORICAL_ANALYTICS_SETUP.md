# Historical Analytics Setup (PostgreSQL Layer)

This project now supports a durable historical analytics layer without changing SQLite runtime DB usage.

## 1) Install PostgreSQL driver

Recommended:

```bash
pip install "psycopg[binary]"
```

Alternative:

```bash
pip install psycopg2-binary
```

## 2) Environment Variables

Set in your env file (`config_env/primary.env` or runtime env):

```env
HISTORICAL_PG_ENABLED=1
HISTORICAL_PG_DSN=postgresql://user:password@localhost:5432/shoonya_history
HISTORICAL_SAMPLING_SEC=3
HISTORICAL_OPTION_SAMPLING_SEC=10
```

## 3) Auto-created tables

On startup, service creates:
- `strategy_samples`
- `strategy_events`
- `index_ticks`
- `option_chain_metrics`

## 4) APIs

- `GET /dashboard/analytics/history/health`
- `GET /dashboard/analytics/history/strategy-samples?strategy_name=...&from_ts=...&to_ts=...`
- `GET /dashboard/analytics/history/strategy-events?strategy_name=...&from_ts=...&to_ts=...`
- `GET /dashboard/analytics/history/index-ticks?symbols=NIFTY,BANKNIFTY&from_ts=...&to_ts=...`
- `GET /dashboard/analytics/history/option-metrics?exchange=NFO&symbol=NIFTY&expiry=...&from_ts=...&to_ts=...`

## 5) UI

- `strategy.html` Analytics tab now has replay controls:
  - Load Replay (from durable history)
  - Play/Pause timeline replay
- `option_chain_analytics.html` now includes historical trend chart from PostgreSQL.

## 6) Notes

- If PostgreSQL env is disabled/missing, existing live features continue to work.
- Replay/history APIs return 503 when historical layer is disabled.
- SQLite option-chain DB remains untouched and continues as live snapshot source.
