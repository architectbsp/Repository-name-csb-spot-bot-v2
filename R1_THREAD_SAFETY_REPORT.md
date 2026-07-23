# R1 — Thread Safety Hardening Report

**Sprint:** `R1_THREAD_SAFETY_HARDENING`  
**Scope:** Shared mutable state only — no redesign, no trading/behavior/API changes.  
**Date:** 2026-07-23

---

## Files changed

| File | Change |
|------|--------|
| `app/core/position_manager.py` | Added `threading.RLock`; all dict / freeze / lifecycle accessors synchronized |
| `app/core/watch_list.py` | Existing `RLock` applied to hot path via `@_coins_locked`; TOCTOU fixed in `add`; strategy callbacks remain outside lock |
| `app/core/event_bus/event_bus.py` | `RLock` on subscriber map; publish snapshots then invokes handlers outside lock |
| `app/core/scheduler/scheduler.py` | `RLock` on `_jobs` / `_running`; `run_pending` snapshots job list then runs outside lock |
| `app/core/worker.py` | Stop flag moved to `threading.Event` (interruptible wait); public start/stop behavior preserved |

**Deliverable:** this file (`R1_THREAD_SAFETY_REPORT.md`).

---

## Why each change was required

### PositionManager
`_positions` was a plain `dict` with **no lock**, mutated from WebSocket → RiskManager paths, Worker/scheduler jobs, and UI dashboard reads. Concurrent `dict` resize/iterate is unsafe and can corrupt state.

### WatchList
An `RLock` existed but was used mainly on list/sync helpers. FSM transitions (`transition`, `begin_*`, `promote_*`, `handle_position_closed`, etc.) and membership checks ran unlocked on the hot path (WS + scan + Worker cooldown). `add()` had a check-then-insert TOCTOU.

### EventBus
`subscribe` / `unsubscribe` / `publish` raced on `_subscribers` (UI wiring vs WS publish). Holding a lock across handlers would deadlock; snapshot-then-call avoids that.

### Scheduler
Worker thread iterates `_jobs` while engine/WatchList may `register`/`unregister`. Unsynchronized dict access.

### Worker
Boolean `_running` + `time.sleep` made stop races / slow stop possible across UI/engine vs daemon thread. `Event` is the standard cross-thread stop primitive without changing tick semantics.

---

## Race conditions discovered

| ID | Location | Classification | Status |
|----|----------|----------------|--------|
| R1 | `PositionManager._positions` concurrent mutate/iterate | **unsafe** | **fixed** (RLock) |
| R2 | `PositionManager._entries_frozen` / lifecycle flags | **unsafe** | **fixed** (same RLock) |
| R3 | `WatchList` FSM / coin dict hot path unlocked | **unsafe** (lock unused) | **fixed** (`@_coins_locked`) |
| R4 | `WatchList.add` check-then-insert TOCTOU | **unsafe** | **fixed** (single critical section) |
| R5 | `EventBus` subscriber list mutate vs publish | **unsafe** | **fixed** (lock + snapshot) |
| R6 | `Scheduler._jobs` Worker vs register | **unsafe** | **fixed** (lock + snapshot) |
| R7 | `Worker._running` / sleep stop | **weakly safe** (CPython bool) | **hardened** (`Event`) |
| R8 | Live `Position` field mutations after `get()` (RiskManager updates attributes outside PM methods) | **unsafe** (object-level) | **remaining** (API/risk logic out of scope) |
| R9 | Sync EventBus handlers still run on WS thread (blocking OES) | **architectural** | **out of scope** (not a shared-state race; latency/starvation) |
| R10 | `RiskManager._entries_frozen` separate from PM | **minor** | **remaining** (risk logic out of scope) |
| R11 | `DashboardService` / OES / telemetry | **already synchronized** | unchanged |
| R12 | Price stream symbol sets | **already synchronized** | unchanged |

---

## Synchronization strategy

1. **Fine-grained RLock per shared container** (`PositionManager`, `WatchList`, `EventBus`, `Scheduler`) — no global lock.
2. **Re-entrant RLock** so nested calls (`begin_*` → `transition` → `can_transition`) do not self-deadlock.
3. **Callbacks / I/O outside locks where possible:**
   - EventBus: snapshot subscribers under lock → invoke outside.
   - Scheduler: snapshot jobs under lock → `run_job` outside.
   - WatchList: `sync_price_stream` / `strategy.on_ticker` outside coin lock.
   - WatchList `handle_price_update` / `handle_scan_result`: brief locked membership/state ops only; strategy unlocked.
4. **Lock order (documented):** never hold WatchList lock across strategy/Risk/PositionManager. EventBus never holds lock across handlers. Prevents WL→PM vs UI PM→WL deadlock.

---

## Deadlock analysis

| Scenario | Result |
|----------|--------|
| WS: WL strategy → PM.add → EventBus.publish → WL.handle_position_closed | Safe: WL lock not held across strategy; EventBus lock released before handlers; WL RLock re-entry if same thread later |
| UI: PM.get_open_positions then WL.list_by_states | Safe: each method acquires/releases its own lock; no cross-hold |
| Worker: Scheduler.tick → job → WL.process_cooldowns while WS holds WL briefly | Safe: short critical sections; fair wait |
| Handler subscribe during publish | Safe: publish uses snapshot; subscribe waits only for map mutation |
| Job register during `run_pending` | Safe: job list snapshotted; register uses lock after snapshot |

No multi-lock hold cycles introduced.

---

## Remaining risks

1. **Position object field races (R8):** callers may mutate `Position` attributes after `get()` without holding `PositionManager._lock`. Dict integrity is protected; torn multi-field updates remain possible. Fix would require risk-layer locked update APIs (out of scope).
2. **WS-thread blocking (R9):** sync EventBus + OES on WS thread can stall price updates — concurrency/latency issue, not dict corruption.
3. **SQLite / persistence concurrency:** out of scope (no WAL changes this sprint).
4. **RiskManager `_entries_frozen`:** not wrapped; rare freeze/check race.
5. **Minimal contention:** repository `save` still occurs under `PositionManager` lock on add/close/scale_out/persist — correct for consistency; can briefly delay UI readers during I/O.

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
401 passed, 2 warnings in 8.87s
PYTEST_EXIT: 0
```

(Warnings are pre-existing SQLAlchemy datetime deprecations in migration tests.)

### Runtime

- Import/wiring smoke for PositionManager, WatchList, EventBus, Scheduler, Worker: **OK**
- `main.py` launched and remained alive ≥5s (Flet UI process), then terminated: **OK**

---

## Final audit

### Critical Remaining Issues
- None for shared **container** integrity (dicts / subscriber maps / job maps) covered by this sprint.

### Major Remaining Issues
- Live `Position` field mutations outside `PositionManager` methods (R8) — requires risk-layer cooperation in a later sprint.
- Blocking work on WebSocket callback thread via sync EventBus (R9) — operational risk under load; architectural, out of R1 scope.

### Minor Remaining Issues
- `RiskManager._entries_frozen` unsynchronized (R10).
- Repository I/O under PM lock can briefly increase UI wait (contention, not correctness).

---

## THREAD SAFETY STATUS:
**PRODUCTION READY** for shared mutable **container** state (PositionManager dict, WatchList coins, EventBus subscribers, Scheduler jobs, Worker stop).

Object-level Position field races and WS-thread blocking remain known residual risks outside this sprint’s mandate; they do not reopen the dict-corruption class of bugs R1 targeted.
