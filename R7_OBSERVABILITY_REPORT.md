# R7 — Production Observability Report

**Sprint:** `R7_PRODUCTION_OBSERVABILITY`  
**Scope:** Runtime health diagnostics only  
**Behavior preservation:** Mandatory — no Strategy / RiskManager / exchange redesign / SQLite schema / UI redesign / architecture cleanup  
**Date:** 2026-07-23

---

## 1. Health signals

Operators can call `BotEngine.health_snapshot()` (also mirrored into `runtime_health`) and immediately answer:

| Question | Signal |
|----------|--------|
| Is the bot alive? | `alive` / `mode` |
| Is every worker alive? | `worker.thread_alive`, `worker.active`, `worker.stall_seconds` |
| Is Exchange connected? | `exchanges.any_connected`, per-venue `status` / `last_error` (redacted) |
| Is WebSocket alive? | `websocket.ok`, `data_age_seconds`, per-venue `ws_connected` / `ws_running` |
| Is Scheduler running? | `scheduler.running` |
| Are jobs delayed? | `scheduler.delayed_jobs`, per-job `overdue_seconds` / `delayed` |
| Are orders flowing? | `orders.flowing` (recent order latency samples) |
| Is recovery active? | `recovery.attention`, quarantine list, active ClientOrderId statuses |
| Is persistence / DB healthy? | `persistence.ok` via throttled `PRAGMA quick_check` |
| Is EventBus healthy? | `event_bus.handler_errors`, `publish_count`, `topic_count` |
| Is runtime degraded? | `degraded` + `issues[]` |

---

## 2. Metrics

Reused from existing `TelemetryService.collect()` (no trading mutation):

- `order_latency_ms`, `api_latency_ms`, `data_age_seconds`
- `scan_elapsed_ms` / `pipeline_ms`
- `ram_mb`, `cpu_percent`

New lightweight counters:

- EventBus `publish_count` / `handler_errors` / `topic_count`
- Price stream `connected` property (WS handshake)

---

## 3. Runtime diagnostics

**Primary API:** `BotEngine.health_snapshot() -> dict`  
**Aggregator:** `app/core/services/runtime_health.py` (`RuntimeHealthService`)

Also updates `BotEngine.runtime_health` with:

- `degraded`, `mode`, `issues`, `last_health_at`
- `exchange_connected`, `websocket_ok`, `scheduler_ok`, `persistence_ok`, `recovery_attention`

All error strings pass through `redact_secrets` (R6).

---

## 4. Failure detection

| Condition | Issue code |
|-----------|------------|
| Worker thread dead / inactive while bot running | `worker_thread_dead` / `worker_inactive` |
| Worker tick stall > 30s | `worker_stalled` |
| Worker consecutive errors ≥ 3 | `worker_error_burst` |
| Scheduler stopped while bot running | `scheduler_stopped` |
| Job overdue > 2× interval | `scheduler_jobs_delayed` |
| No enabled venue CONNECTED | `exchange_disconnected` |
| Venue ERROR | `exchange_error` |
| Ticker age > 60s | `websocket_stale` |
| WS expected running but no data age | `websocket_inactive` |
| Active ClientOrderId AMBIGUOUS / AWAITING_LOCAL | `recovery_unresolved` |
| SQLite quick_check not ok | `persistence_unhealthy` |

Quarantine-only markets set `recovery.attention` without forcing degraded (protective state).

---

## 5. Remaining blind spots

| Blind spot | Severity |
|------------|----------|
| No dedicated HTTP `/health` endpoint (desktop app; snapshot is in-process) | Major (ops integration) |
| Telegram `/status` not yet printing the new snapshot | Minor |
| Dashboard UI does not paint the new fields (UI redesign out of scope) | Minor |
| EventBus has no queue depth (sync bus; counters only) | Minor |
| DB quick_check throttled to ≥60s between probes | Minor |
| Multi-venue OR “any connected” may hide one down venue unless operators read `venues[]` | Minor |

---

## 6. Files changed

- `app/core/services/runtime_health.py` (new)
- `app/core/bot_engine.py` — `health_snapshot()`, service wire-up
- `app/core/event_bus/event_bus.py` — stats counters
- `app/core/persistence/database.py` — `sqlite_quick_check_status`
- `app/core/services/order_execution.py` — `list_active_client_orders` (read-only)
- `app/core/exchange/ws_price_stream_base.py` / `binance_price_stream.py` — `connected`
- `tests/test_runtime_health.py` (new)

**Not modified:** Strategy, RiskManager logic, exchange trading paths, SQLite schema, UI, recovery algorithms.

---

## 7. Compile result

```text
.venv/bin/python -m compileall -q app
COMPILE_EXIT: 0
```

---

## 8. Test result

```text
.venv/bin/python -m pytest -q
436 passed, 2 warnings
```

---

## 9. Runtime result

```text
python main.py
remained alive ≥5s after launch
RUNTIME: OK
```

---

## 10. Final audit

### Critical Remaining Issues

- None for in-process operator diagnosis via `health_snapshot()`.

### Major Remaining Issues

1. No external HTTP health probe (process must be inspected in-app / via future thin wrapper).

### Minor Remaining Issues

1. Telegram/Dashboard not yet surfacing the snapshot (out of UI redesign scope).
2. Per-venue disconnect can be masked if another venue is CONNECTED (full detail still in `venues[]`).
3. EventBus health is counter-based only.

---

## OBSERVABILITY STATUS:

**PRODUCTION READY**
