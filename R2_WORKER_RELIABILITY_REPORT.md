# R2 — Worker Reliability Report

**Sprint:** `R2_WORKER_RELIABILITY`  
**Depends on:** R1 Thread Safety (approved)  
**Scope:** Background worker reliability only — no redesign, no trading/behavior changes.  
**Date:** 2026-07-23

---

## Workers audited

| Component | Type | How driven | Pre-R2 failure visibility |
|-----------|------|------------|---------------------------|
| `Worker` (`app/core/worker.py`) | Daemon thread | `Scheduler.tick` loop | **Hidden** — `except Exception: pass` |
| `Scheduler` jobs | Callbacks on Worker thread | MarketScanner, WatchList cooldown, Telegram tick, PositionReconciler, Risk duration | Job exceptions bubbled then swallowed by Worker |
| MarketScanner | Scheduler job | `tick` / `scan_once` | Per-venue fetch logged; tick raise → silent via Worker |
| WatchList `process_cooldowns` | Scheduler job | Worker | Failures silent via Worker |
| TelegramNotifier `tick` | Scheduler job | Worker | Probe `except: return` silent; tick uncaught → Worker swallow |
| PositionReconciler | Scheduler job | Worker | Already `logger.exception` on reconcile errors |
| EventBus handlers | Sync on publisher thread (often WS) | WS / engine | Already logged in EventBus |
| WS price streams | Background + keepalive threads | Exchange streams | Errors mostly logged; `ws.close()` used bare `pass` |
| BinancePriceStream | Dedicated thread | Exchange | Same close `pass` |
| UI `coin_chart` auto-refresh | Daemon thread | Flet UI | Out of scope (UI); logged on build failures |
| `Timer` | In-process stopwatch | No thread | N/A |

---

## Hidden failures found

| ID | Location | Issue | Severity |
|----|----------|-------|----------|
| H1 | `Worker._run` | `except Exception: pass` — tick/job failures invisible | **Critical** |
| H2 | `Scheduler.run_job` | No logging; failures only surfaced if caller logged | **Major** |
| H3 | `Job` | No `last_error` field for operators/health | **Major** |
| H4 | `BotEngine` | No worker health / no `worker.error` / `worker.fatal` notify | **Major** |
| H5 | `Worker.stop` | Join from inside worker thread would deadlock fatal→`stop()` | **Major** (latent) |
| H6 | Telegram `_probe_exchange_status` | `except Exception: return` with no log | **Minor** |
| H7 | WS `close()` during stop | bare `except: pass` | **Minor** |
| H8 | UI chart refresh daemon | Separate UI concern | **Out of scope** |

---

## Fixes applied

| File | Fix |
|------|-----|
| `app/core/worker.py` | Log tick failures; `on_error` / `on_fatal` callbacks; `WorkerHealth`; error counters; unexpected-exit detection; stop() does not join self |
| `app/core/scheduler/scheduler.py` | Log job failures with job name; re-raise to Worker; clear/set `job.last_error` |
| `app/core/scheduler/job.py` | Add `last_error` field |
| `app/core/bot_engine.py` | `runtime_health` dict; wire Worker callbacks; publish `worker.error` / `worker.fatal`; fatal → graceful `stop()` on helper thread |
| `app/core/services/telegram_notifier.py` | Log probe failures; wrap `tick` with log + re-raise |
| `app/core/exchange/ws_price_stream_base.py` | Log close failures at debug (no longer silent) |
| `app/core/exchange/binance_price_stream.py` | Same for Binance close |
| `tests/test_worker.py` | Notify / survive / `last_error` coverage |

Trading logic, strategy, risk, execution flow, and public trading APIs unchanged.

---

## Worker lifecycle

```
BotEngine.start()
  → scheduler.start()
  → worker.start()          # daemon SchedulerWorker thread
       loop:
         scheduler.tick()   # run due jobs
         on job Exception:
           Scheduler logs + job.last_error
           Worker logs + health counters
           on_error → BotEngine._on_worker_error
             → runtime_health update
             → EventBus "worker.error"
         wait(interval)     # interruptible Event
  → … exchange / streams …

BotEngine.stop()
  → worker.stop()           # set Event, clear active, join (not self)
  → scheduler.stop()

Fatal path (unexpected thread death while still expected to run):
  → Worker logs CRITICAL + on_fatal
  → BotEngine publishes "worker.fatal"
  → helper thread calls BotEngine.stop()  # clean shutdown, no self-join
```

---

## Shutdown verification

- Normal `stop()`: interruptible wait, join with timeout, `_active` cleared before join → no false `worker.fatal`.
- Fatal→`stop()` from worker context: `Worker.stop()` skips self-join; engine stop runs on `BotEngineWorkerFatalShutdown` thread.
- Tests: start/stop + repeated failures leave thread alive until explicit stop.

---

## Validation results

### Compile

```text
.venv/bin/python -m compileall -q app
COMPILE_EXIT: 0
```

### Tests

```text
.venv/bin/python -m pytest -q --tb=line
404 passed, 2 warnings
```

(3 new worker reliability tests; prior suite green.)

### Runtime

- `main.py` remained alive ≥4s after launch (Flet process), then force-stopped for smoke.
- Workers continue after non-fatal job errors (covered by unit tests).

---

## Final audit

### Critical Remaining Issues
- None for silent Worker/`except: pass` on the scheduler daemon path.

### Major Remaining Issues
- Sync EventBus handlers still execute on the WebSocket thread; a hung handler can stall the stream (latency), but failures are already logged by EventBus — architectural, out of R2 scope.
- Position object field races (R1 residual) — unrelated to worker reliability.

### Minor Remaining Issues
- UI `coin_chart` auto-refresh daemon not instrumented (UI out of scope).
- WS reconnect loops do not publish a dedicated `worker.*` health event (exchange stream health uses existing `exchange.disconnected` / logs).

---

## WORKER RELIABILITY STATUS:
**PRODUCTION READY**
