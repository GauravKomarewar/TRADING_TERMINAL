# Historical Analytics Implementation Tracker

## Goal
Add a **durable PostgreSQL historical layer** (SQLite remains untouched) for:
- strategy telemetry history
- strategy lifecycle events (entry/adjustment/exit)
- ticker ribbon/index history
- option chain analytics history
- replay mode in strategy analytics UI

## Constraints
- Do not modify current SQLite runtime data flow.
- Historical layer must be optional at startup (controlled by env).
- APIs should return clear error when historical DB is unavailable.

## Phases

### Phase 1: Foundation
- [x] Add PostgreSQL config env support
- [x] Add historical DB store module (DDL + insert/query)
- [x] Add robust connection handling + health checks

### Phase 2: Ingestion
- [x] Add background historical analytics service (thread)
- [x] Ingest strategy telemetry snapshots periodically
- [x] Detect and store strategy events (ENTRY/ADJUSTMENT/EXIT)
- [x] Ingest ticker/index ribbon snapshots periodically
- [x] Ingest option chain derived metrics periodically

### Phase 3: API
- [x] Add history health endpoint
- [x] Add strategy history endpoint
- [x] Add strategy events endpoint
- [x] Add index/ticker history endpoint
- [x] Add option chain metrics history endpoint

### Phase 4: Replay UI
- [x] Extend strategy analytics tab with replay controls
- [x] Load durable history into chart
- [x] Support time-window playback (play/pause/seek)
- [x] Keep live mode fallback when replay is off

### Phase 5: Validation
- [ ] Static checks / compile checks
- [ ] Smoke test endpoints
- [ ] Smoke test UI JS parse
- [x] Document env setup + usage

## Notes
- `psycopg` (or `psycopg2`) must be installed in runtime environment.
- Recommended env vars:
  - `HISTORICAL_PG_ENABLED=1`
  - `HISTORICAL_PG_DSN=postgresql://user:pass@host:5432/dbname`
  - `HISTORICAL_SAMPLING_SEC=3`
  - `HISTORICAL_OPTION_SAMPLING_SEC=10`

