# R4 — Order Integrity & Reconciliation Report

**Sprint:** `R4_ORDER_INTEGRITY_AND_RECONCILIATION`  
**Depends on:** R1 / R2 / R3 (approved)  
**Scope:** Order lifecycle integrity + exchange reconciliation only.  
**Date:** 2026-07-23

---

## Lifecycle audit

| Exchange / outcome state | Pre-R4 handling | Post-R4 |
|--------------------------|-----------------|---------|
| `NEW` / `OPEN` | Pending poll → cancel → clean `TIMED_OUT` | Unchanged poll; **post-cancel `fetch_order` verify** |
| `PARTIALLY_FILLED` | Treated as open; cancel ignored fills | Partial qty tracked; full qty ⇒ `FILLED`; cancel with fill ⇒ `UNRECONCILED` + quarantine |
| `FILLED` / `CLOSED` | `FILLED` | Same; also detected after cancel race |
| `CANCELED` / `CANCELLED` / `REJECTED` / `EXPIRED` | `REJECTED` if no pending path | + `FAILED`; terminal **with fill** ⇒ `UNRECONCILED` |
| Submit `TIMEOUT` | Ambiguous `TIMED_OUT` + quarantine | Same |
| `NETWORK_FAILED` | Quarantine | Same |
| `UNKNOWN` / `None` | `UNKNOWN_STATUS` + quarantine | Same |
| Cancel success (no verify) | Assumed zero inventory | **Re-fetch required** before `TIMED_OUT` |
| Restart after quarantine | Lost (memory only) | **JSON sidecar** reload |
| Orphan inventory (no local OPEN) | Not detected | Quarantined markets probed for free base > dust |

Terminal destination for every order path: **confirmed** (`FILLED` / clean `REJECTED` / clean `TIMED_OUT`), **reconciled** (balance OK), **quarantined** / **recovered via operator `clear_quarantine`**, or **UNRECONCILED** (observable + quarantined).

---

## Reconciliation strategy

1. **Per-order (OES)**  
   - Poll open/partial orders.  
   - Promote to `FILLED` when status filled **or** `filled_quantity >= requested`.  
   - On pending timeout: cancel, then **`_verify_after_cancel`**.  
   - Ambiguous outcomes → quarantine + `on_ambiguous` → `PositionReconciler.reconcile_once()`.

2. **Periodic / on-ambiguous (PositionReconciler)**  
   - **LOCAL_GT_EXCHANGE:** OPEN local qty ≫ free base → quarantine + events.  
   - **ORPHAN_INVENTORY:** quarantined market, no local OPEN, free base > dust → events (already quarantined).

3. **Durable quarantine**  
   - Optional JSON sidecar (`{sqlite_path}.quarantine.json`) via `set_quarantine_store_path` (BotEngine wires from DB URL).  
   - Survives restart without SQLite schema changes.

---

## Edge cases covered

| Scenario | Coverage |
|----------|----------|
| Partial fill then cancel | `UNRECONCILED` + quarantine |
| Cancel/fill race | Post-cancel fetch → `FILLED` |
| Clean cancel (zero fill) | `TIMED_OUT`, not ambiguous |
| Cancel then fetch fails | `UNRECONCILED` |
| Unknown status | `UNKNOWN_STATUS` + quarantine |
| Duplicate in-process | Existing in-flight / open BUY guard |
| Restart after quarantine | Sidecar reload blocks new orders |
| Orphan inventory | Reconciler orphan probe |
| Local position without exchange qty | Existing shortfall reconcile |

---

## Recovery strategy

| Condition | Action |
|-----------|--------|
| Confirmed fill after cancel race | Return `FILLED` (RiskManager may open/close normally) |
| Partial / unknown / unreconciled | Quarantine market; publish `order.needs_manual_review` / mismatch |
| Operator verified exchange | `clear_quarantine(market_key)` |
| Process restart | Quarantine set restored from sidecar; reconciler continues on schedule |

---

## Files changed

- `app/core/services/order_execution.py` — verify-after-cancel, partial/full fill classification, `FAILED`, quarantine store
- `app/core/services/position_reconciler.py` — orphan inventory probe
- `app/core/bot_engine.py` — quarantine store path wiring
- `tests/test_order_execution.py` — cancel race, partial, store reload
- `tests/test_position_reconciler.py` — orphan case

---

## Remaining risks

1. **Submit timeout / network fail without `order_id`** — still cannot poll; relies on quarantine + orphan balance probe (no `fetch_open_orders` scan; exchange API expansion out of scope).
2. **Cross-process duplicate** — in-flight guard is per-process; client-order-id idempotency not added (would touch exchange submit contract).
3. **Orphan detection only for quarantined markets** — intentional to avoid full-wallet scans; un-quarantined silent deposits still need operator/manual review.
4. **RiskManager sell uses `is_filled` only** — unchanged (out of scope); OES no longer returns clean `TIMED_OUT` with hidden fills.

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
412 passed, 2 warnings
```

Targeted: partial fill after cancel, cancel race fill, clean cancel, quarantine store reload, orphan reconcile — covered in unit tests.

### Runtime
- `main.py` alive ≥4s: **OK**

---

## Final audit

### Critical Remaining Issues
- None for cancel/partial/timeout silent inventory loss on the OES path covered above.

### Major Remaining Issues
- Ambiguous submit without `order_id` still cannot auto-attach to an exchange order (quarantine + orphan probe only).
- No client-order-id idempotency across process restarts mid-submit.

### Minor Remaining Issues
- Orphan probe limited to quarantined markets (by design).

---

## ORDER INTEGRITY STATUS:
**PRODUCTION READY**
