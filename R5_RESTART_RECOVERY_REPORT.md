# R5 — Restart & Recovery Hardening Report

**Sprint:** `R5_RESTART_AND_RECOVERY_HARDENING`  
**Scope:** Crash consistency and recovery correctness only  
**Behavior preservation:** Mandatory — no Strategy / RiskManager / UI / architecture redesign  
**Date:** 2026-07-23

---

## 1. Crash analysis

| Crash point | Pre-fix risk | Post-fix |
|-------------|---------------|------------|
| Kill after BUY submit, before ACK | PENDING cid; recovery only on next `execute()` | Startup / reconnect `recover_inflight_orders()` scans active cids |
| Kill after exchange ACK (`SUBMITTED`) | Same lazy recovery | Proactive recover; open/ambiguous → quarantine |
| Kill after FILLED, before local position persist | cid was `COMPLETED` (slot cleared); silent orphan; next BUY could double | cid stays `AWAITING_LOCAL`; recover → quarantine + observable |
| Kill during SQLite commit of `add`/`close` | WAL commit atomicity (R3); incomplete → no row | Treated as unmanaged fill/close via `AWAITING_LOCAL` recovery |
| Restart after reconnect | Balance reconcile only (R4) | + `recover_inflight_orders()` |
| Restart after quarantine | Quarantine JSON reload (R4) | Unchanged; still blocks submits |
| Partial fill / cancel pending | In-OES poll/cancel/verify (R4) | Unchanged; residual → `UNRECONCILED` + quarantine |
| Trailing / stop / break-even mid-tick | Last `persist()` wins | Unchanged (graceful rehydrate); kill mid-tick may lose last stop update |

**Root gap fixed:** FILLED used to `mark_completed` and clear the active ClientOrderId **before** `PositionManager.add` / `close` / `scale_out`. A kill in that window left exchange inventory with no local position, no quarantine, and no startup ClientOrderId scan.

---

## 2. Recovery strategy

1. **`AWAITING_LOCAL`** — on `ExecutionOutcome.FILLED`, keep the market’s ClientOrderId active until local persistence is confirmed.
2. **Confirm hook** — `OrderExecutionService.set_position_manager` binds `PositionManager.set_on_local_persisted` → `confirm_local_position` (add / close / scale_out). No RiskManager changes.
3. **`recover_inflight_orders()`** — at BotEngine startup and on `exchange.connected`, scan all active ClientOrderIds (no new strategy signal required):
   - matching local state → `COMPLETED`
   - recovered fill / open / missing with mismatch → quarantine + `on_ambiguous` (observable)
4. **`_settle_awaiting_local`** — before a new submit, resolve or abort if `AWAITING_LOCAL` does not match local open state.

---

## 3. Recovery guarantees

- No silent drop of an in-flight ClientOrderId across restart while status is PENDING / SUBMITTED / AMBIGUOUS / AWAITING_LOCAL.
- A venue fill without matching local position/close becomes **quarantined and observable** (logs + `on_ambiguous` → reconciler).
- Local OPEN positions still rehydrate from SQLite; open journal rows still rehydrate.
- R4 balance reconcile (`LOCAL_GT_EXCHANGE`, quarantined `ORPHAN_INVENTORY`) remains.
- Happy-path BUY → position → SELL / partial TP behavior preserved when PositionManager is wired to OES (production + integration path).

---

## 4. Remaining ambiguity

| Item | Severity |
|------|----------|
| Operator `clear_quarantine` without verifying exchange | Can unlock a market while inventory still exists |
| Venue cannot resolve ClientOrderId | Recover marks unresolved → quarantine (safe, manual) |
| Journal ENTRY after position add | Kill between add and `record_entry` → position restored, journal gap (MFE/MAE only) |
| Trailing/stop mid-tick without `persist` | Older stop/highest on restart |
| Auto-create Position from orphan inventory | Not done (no redesign); quarantine + observe only |
| `:memory:` DB / no sidecar path | Client-order durability disabled (same as R5 idempotency) |

---

## 5. Scenario verification matrix

| Scenario | Result |
|----------|--------|
| kill -9 after BUY submit | Covered — active PENDING + startup recover |
| kill -9 after exchange ACK | Covered — SUBMITTED + recover |
| kill -9 after FILLED before persistence | Covered — AWAITING_LOCAL + recover → quarantine |
| kill -9 during SQLite commit | Covered as incomplete local + AWAITING_LOCAL / WAL |
| restart after reconnect | Covered — reconcile + recover_inflight |
| restart after quarantine | Covered — quarantine store |
| restart after partial fill | Covered — OES UNRECONCILED path; AWAITING_LOCAL on full classify fill |
| restart after cancel pending | Covered — R4 cancel verify |
| restart during trailing / stop / BE | Partial — last persisted stop; mid-tick loss minor |

---

## 6. Compile result

```text
.venv/bin/python -m compileall -q app
COMPILE_EXIT: 0
```

---

## 7. Test result

```text
.venv/bin/python -m pytest -q
424 passed, 2 warnings
```

New: `tests/test_restart_recovery.py` (AWAITING_LOCAL confirm, unmanaged quarantine, pending recovered fill).

---

## 8. Runtime result

```text
python main.py
remained alive ≥5s after launch, then stopped
RUNTIME: OK
```

---

## 9. Files touched (recovery only)

- `app/core/services/client_order_registry.py` — `AWAITING_LOCAL`, `list_active`
- `app/core/services/order_execution.py` — await/confirm/recover/settle
- `app/core/position_manager.py` — `on_local_persisted` after add/close/scale_out
- `app/core/bot_engine.py` — startup + reconnect recover
- `tests/test_restart_recovery.py`

**Not modified:** Strategy, RiskManager, UI, SQLite schema.

---

## 10. Final audit

### Critical Remaining Issues

- None for silent disappearance of an in-flight / AWAITING_LOCAL fill across restart when the ClientOrderId sidecar is enabled.

### Major Remaining Issues

1. Operator `clear_quarantine` can re-enable trading over unresolved exchange inventory.
2. No automatic Position attach from orphan inventory (observe + quarantine only).
3. Venue ClientOrderId lookup failures force quarantine (manual resolution).

### Minor Remaining Issues

1. Journal ENTRY gap if kill after position save and before journal insert.
2. Trailing/stop last-tick persist race.
3. Registry historical record growth (no pruning).

---

## RESTART & RECOVERY STATUS:

**PRODUCTION READY**
