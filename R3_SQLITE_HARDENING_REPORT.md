# R3 — SQLite Hardening Report

**Sprint:** `R3_SQLITE_HARDENING`  
**Depends on:** R1 Thread Safety, R2 Worker Reliability (approved)  
**Scope:** SQLite persistence reliability / durability / correctness only.  
**Date:** 2026-07-23

---

## Database settings

Applied on every new SQLite DB-API connection (`connect` event):

| PRAGMA / connect arg | Value | Purpose |
|----------------------|-------|---------|
| `journal_mode` | `WAL` | Concurrent readers + one writer (UI / Worker / WS) |
| `busy_timeout` | `5000` ms | Bounded wait instead of immediate `SQLITE_BUSY` |
| `foreign_keys` | `ON` | Enforce FK constraints (off by default in SQLite) |
| `synchronous` | `NORMAL` | WAL-recommended durability balance |
| `check_same_thread` | `False` | Shared engine across Flet + Worker threads |
| `timeout` (pysqlite) | `30` s | Complements busy_timeout at driver level |

**Pool strategy**

| URL | Pool | Rationale |
|-----|------|-----------|
| File SQLite | `NullPool` | No long-held pooled connections → less lock amplification |
| `:memory:` | `StaticPool` | Single shared in-memory connection for engine lifetime |
| Postgres / MariaDB | default + `pool_pre_ping` | Unchanged |

---

## Engine changes

**File:** `app/core/persistence/database.py`

- `create_db_engine()` registers SQLite PRAGMA listener.
- `configure_database()` **disposes** the previous process-wide engine before swap.
- `verify_sqlite_integrity()` runs `PRAGMA quick_check` (fail-fast on corruption).
- `checkpoint_sqlite_wal()` runs `PRAGMA wal_checkpoint(TRUNCATE)` on shutdown.
- `dispose_database()` for process-level cleanup.

**File:** `app/core/persistence/service.py`

- Calls `verify_sqlite_integrity()` after `sync_schema()` on construct.
- `dispose()` checkpoints WAL then `engine.dispose()`.
- `load_positions()` closes the one-shot repository session in `finally`.

**File:** `app/core/bot_engine.py`

- `stop()` calls `persistence.dispose()` for shutdown consistency (persistence lifecycle only).

---

## Session lifecycle

| Before R3 | After R3 |
|-----------|----------|
| Repositories keep a long-lived `Session` | Same API (behavior preserved) |
| Failed `commit()` could leave session unusable | `_commit()` rolls back then re-raises |
| `load_positions()` left session open | Session closed after list |
| Engine rebuild leaked old pools | Previous engine disposed |
| Process stop left WAL / connections | Checkpoint + dispose |

Optional `Repository.close()` added for explicit cleanup; existing callers unchanged.

---

## Transaction strategy

- **Unchanged commit points** — same `save` / `delete` / `insert` / `update` boundaries (no trading-visible durability change except safer failure recovery).
- **Rollback safety:** every repository write goes through `_commit()` → on error `rollback()` then re-raise.
- **Autocommit:** still `False`; `autoflush=False`; `expire_on_commit=True` (SQLAlchemy default, now explicit).

---

## Recovery behavior

| Phase | Behavior |
|-------|----------|
| Startup | `sync_schema()` then `PRAGMA quick_check`; non-`ok` → `RuntimeError` + critical log |
| Lock contention | `busy_timeout` + pysqlite `timeout` retry wait |
| Shutdown | `wal_checkpoint(TRUNCATE)` then `dispose()` |
| Engine hot-swap | Prior engine disposed |

---

## Lock analysis

- **WAL** allows concurrent readers during a write; writers still serialize.
- **NullPool** avoids multiple idle write-capable connections sitting in a QueuePool.
- **busy_timeout=5000** absorbs short Worker/UI write collisions without failing the first waiter immediately.
- Commit frequency unchanged → no new lock amplification from extra commits.

---

## Remaining risks

1. **Long-lived repository sessions** (PositionManager / TradeJournal / Settings) still hold a Session for process life — mitigated by rollback-on-error and NullPool release after commit, but not full unit-of-work redesign (out of scope).
2. **Persist-per-tick** from Risk/PositionManager can still write often under load — frequency is trading-path behavior, not changed here.
3. **Non-SQLite backends** unchanged aside from existing `pool_pre_ping`.

---

## Files changed

- `app/core/persistence/database.py`
- `app/core/persistence/service.py`
- `app/core/persistence/repository.py`
- `app/core/bot_engine.py` (dispose on stop only)
- `tests/test_sqlite_hardening.py` (new)
- `tests/test_full_integration.py` (NullPool-aware leak assert)

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
408 passed, 2 warnings
```

### Runtime

- WAL / integrity / checkpoint smoke on temp file DB: **OK**
- `main.py` remained alive ≥4s: **OK**

---

## Final audit

### Critical Remaining Issues
- None for SQLite durability settings, lock wait, integrity gate, or commit rollback safety.

### Major Remaining Issues
- Immortal repository sessions remain by design (API preserved); a future unit-of-work sprint could scope sessions per operation.

### Minor Remaining Issues
- High-frequency position persist still generates many commits (trading-path, out of scope).

---

## SQLITE STATUS:
**PRODUCTION READY**
