# R4 — Order Integrity & Reconciliation Report

**Sprint:** `R4_ORDER_INTEGRITY_AND_RECONCILIATION`  
**Depends on:** R1 / R2 / R3 (approved)  
**Scope:** Order lifecycle integrity, exchange reconciliation, inventory correctness.  
**Date:** 2026-07-23 (updated after full production re-audit)

---

## 1. Order lifecycle audit

Pipeline audited: Strategy → RiskManager → OrderExecutionService → ExchangeManager → Adapter → Response → Persistence → PositionManager → Recovery.

| State | Handling |
|-------|----------|
| `NEW` / `OPEN` | Pending poll → cancel → **post-cancel `fetch_order` verify** |
| `PARTIALLY_FILLED` | Poll; full qty ⇒ `FILLED`; cancel with fill ⇒ `UNRECONCILED` + quarantine |
| `CANCEL_PENDING` / `PENDING_CANCEL` | Treated as open (polled), not `UNKNOWN` |
| `FILLED` / `CLOSED` | `FILLED` (also after cancel/fill race) |
| `CANCELED` / `CANCELLED` / `REJECTED` / `EXPIRED` / `FAILED` | `REJECTED` if zero fill; **with fill ⇒ `UNRECONCILED`** |
| Submit `TIMEOUT` | Ambiguous `TIMED_OUT` + quarantine + reconcile hook |
| `NETWORK_FAILED` | Quarantine |
| `UNKNOWN` / `None` | `UNKNOWN_STATUS` + quarantine |
| Reconnect (`exchange.connected`) | **Triggers `reconcile_once()`** |
| Startup / restart | Positions restored; quarantine sidecar reloaded; **startup `reconcile_once()`** |

Every execution ends as one of: **CONFIRMED** (`FILLED` / clean `REJECTED` / clean zero-fill `TIMED_OUT`), **RECONCILED** (balance OK), **RECOVERED** (operator `clear_quarantine`), **QUARANTINED** / **UNRECONCILED** (observable), or **FAILED**/`NETWORK_FAILED` (quarantined when ambiguous).

---

## 2. Reconciliation strategy

1. **Per-order (OES):** poll → fill classification by status **or** `filled_qty >= requested` → cancel + `_verify_after_cancel`.
2. **Ambiguous hook:** quarantine + `PositionReconciler.reconcile_once()`.
3. **Periodic (120s):** local OPEN vs free base; quarantined orphan inventory.
4. **Reconnect:** `exchange.connected` → reconcile.
5. **Startup:** reconcile immediately after streams start.
6. **Durable quarantine:** JSON sidecar `{sqlite}.quarantine.json` (no SQLite schema change).

---

## 3. Inventory correctness analysis

| Divergence | Detection | Action |
|------------|-----------|--------|
| Local OPEN ≫ exchange free | Periodic / startup / reconnect | Quarantine + `position.reconcile_mismatch` |
| Exchange free, no local OPEN (orphan) | Quarantined markets probed | Events (already quarantined) |
| Partial fill then cancel | Post-cancel verify | `UNRECONCILED` + quarantine |
| Cancel/fill race | Post-cancel fetch shows `FILLED` | Return `FILLED` |
| Clean cancel (0 fill) | Post-cancel verify | `TIMED_OUT` (not ambiguous) |

---

## 4. Partial fill handling

- While open/partial: keep polling; if `filled_quantity >= requested` ⇒ `FILLED`.
- Terminal status with `filled_quantity > 0` ⇒ `UNRECONCILED` (never silent reject).
- After cancel: re-fetch; any residual fill ⇒ `UNRECONCILED` + quarantine.

---

## 5. Restart behavior

| Scenario | Behavior |
|----------|----------|
| Restart after quarantine | Sidecar reloads; new orders blocked until `clear_quarantine` |
| Restart with OPEN positions | Restored from SQLite; startup reconcile vs balances |
| Restart during ambiguous submit (no `order_id`) | Quarantine if persisted; orphan probe on reconcile |
| Restart mid-fill (position not yet persisted) | Orphan may appear under quarantine after reconnect reconcile |

---

## 6. Unknown order handling

- Unrecognized status / `None` result ⇒ `UNKNOWN_STATUS`.
- Always quarantined; `order.needs_manual_review` via Risk alert path when wired.
- Never guessed as filled.

---

## 7. Duplicate protection

| Layer | Mechanism |
|-------|-----------|
| OES in-flight | Per `market_key` set while `execute()` runs |
| OES BUY guard | Blocks if local OPEN already exists |
| RiskManager | Also blocks BUY if local OPEN (unchanged) |
| Duplicate WS tickers | May re-enter strategy; BUY blocked by open position / in-flight / quarantine |
| Cross-process / no clientOrderId | Residual risk (see below) |

REST+WS: order path is REST-only through OES; WS feeds prices into strategy. Race cannot double-submit while in-flight or OPEN; after fill, PositionManager open blocks further BUY.

---

## 8. Remaining risks

1. Submit timeout/network without `order_id` — cannot poll; quarantine + orphan probe only.
2. No client-order-id idempotency across process crash mid-submit.
3. Orphan probe limited to **quarantined** markets (avoids full-wallet scan).
4. Duplicate WS events can still invoke strategy logic; trading guards prevent duplicate BUY, not duplicate CPU work.

---

## 9–11. Validation

### Compile
```text
.venv/bin/python -m compileall -q app
COMPILE_EXIT: 0
```

### Tests
```text
.venv/bin/python -m pytest -q --tb=line
413 passed, 2 warnings
```

Covered unit scenarios: partial fill after cancel, cancel race fill, clean cancel, `CANCEL_PENDING`, unknown status, quarantine store reload, orphan reconcile.

### Runtime
```text
main.py alive ≥4s — OK
```

---

## Files touched (R4 + reconnect hardening)

- `app/core/services/order_execution.py`
- `app/core/services/position_reconciler.py`
- `app/core/bot_engine.py` — quarantine path, startup + reconnect reconcile
- `tests/test_order_execution.py`
- `tests/test_position_reconciler.py`

---

## Final audit

### Critical Remaining Issues
- None for cancel/partial/timeout silent inventory loss on the OES path.

### Major Remaining Issues
- Ambiguous submit without `order_id` cannot attach to exchange order.
- No cross-process client-order-id idempotency.

### Minor Remaining Issues
- Orphan detection only for quarantined markets.
- Duplicate WS ticks still wake strategy (BUY guarded).

---

## ORDER INTEGRITY STATUS:
**PRODUCTION READY**
