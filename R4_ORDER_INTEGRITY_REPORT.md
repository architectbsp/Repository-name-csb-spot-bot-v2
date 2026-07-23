# R4 — Order Integrity Final Audit Report

**Sprint:** `R4_ORDER_INTEGRITY_AND_RECONCILIATION`  
**Mode:** Audit only (no code changes in this pass)  
**Branch HEAD audited:** current workspace (`OrderExecutionService`, `PositionReconciler`, `BotEngine` wiring)  
**Date:** 2026-07-23

---

## 1. Critical Remaining Issues

- None identified for silent inventory loss on the covered OES cancel / partial-fill / post-cancel verify path.
- Ambiguous outcomes with an `order_id` are quarantined and surfaced; clean zero-fill cancels are verified via `fetch_order` before `TIMED_OUT`.

---

## 2. Major Remaining Issues

1. **Submit timeout / network failure without `order_id`** — cannot poll or cancel a specific order; mitigation is quarantine + orphan balance probe on quarantined markets only.
2. **No client-order-id / cross-process idempotency** — in-flight and BUY-open guards are process-local; a crash mid-submit then restart can still risk a second live order before quarantine/reconcile catches up.
3. **Orphan inventory detection is quarantine-scoped** — free-base orphans on markets that were never quarantined are not scanned (by design; no full-wallet walk).

---

## 3. Minor Remaining Issues

1. Duplicate WebSocket `ticker.updated` events can still re-enter strategy; BUY is blocked by open-position / in-flight / quarantine, but CPU work is not deduplicated.
2. Reconciler compares free base only (not locked/in-order balances).
3. Operator recovery still requires manual `clear_quarantine` after exchange verification.

---

## 4. Covered lifecycle states

| State / outcome | Covered how |
|-----------------|-------------|
| `NEW` / `OPEN` | Pending poll → cancel → post-cancel verify |
| `PARTIALLY_FILLED` | Poll; full qty ⇒ `FILLED`; residual after cancel ⇒ `UNRECONCILED` |
| `CANCEL_PENDING` / `PENDING_CANCEL` | Treated as open (polled) |
| `FILLED` / `CLOSED` | `FILLED` (including cancel/fill race) |
| `CANCELED` / `CANCELLED` / `REJECTED` / `EXPIRED` / `FAILED` | Zero fill ⇒ `REJECTED`; with fill ⇒ `UNRECONCILED` |
| Submit `TIMEOUT` | Ambiguous `TIMED_OUT` + quarantine |
| `NETWORK_FAILED` | Quarantine |
| `UNKNOWN` / `None` | `UNKNOWN_STATUS` + quarantine |
| `DUPLICATE` / `QUARANTINED` | Pre-exchange block |
| `UNRECONCILED` | Cancel failures / residual fill / post-cancel fetch failure |

---

## 5. Covered reconciliation scenarios

- Local OPEN quantity ≫ exchange free base → quarantine + events (`LOCAL_GT_EXCHANGE`).
- Quarantined market, no local OPEN, free base > dust → orphan events (`ORPHAN_INVENTORY`).
- Ambiguous OES outcome → quarantine store + `on_ambiguous` → `reconcile_once()`.
- Startup after position restore → `reconcile_once()`.
- `exchange.connected` (WS reconnect) → `reconcile_once()`.
- Periodic scheduler job (~120s).
- Quarantine persistence across restart (JSON sidecar).

---

## 6. Remaining unhandled scenarios

- Attach/recover a live exchange order after submit timeout when no `order_id` was returned (`fetch_open_orders` scan not implemented).
- Cross-process duplicate submit with client-order-id.
- Orphan inventory on non-quarantined markets.
- Locked/in-order balance vs free-balance nuance.
- Automatic position creation from detected orphan inventory (operator-driven only).

---

## 7. Compile result

```text
.venv/bin/python -m compileall -q app
COMPILE_EXIT: 0
```

---

## 8. Test result

```text
.venv/bin/python -m pytest -q --tb=line
413 passed, 2 warnings
PYTEST_EXIT: 0
```

(Warnings: pre-existing SQLAlchemy datetime deprecation in migration tests.)

---

## 9. Runtime result

```text
main.py remained alive ≥4s after launch
RUNTIME: OK
```

---

## 10. Final verdict

R4 controls prevent the previously critical silent paths (cancel assuming zero fill, partial fill ignored, reconnect/startup skipping reconcile, ephemeral quarantine). Remaining gaps are residual recovery edges without `order_id` and cross-process idempotency — observable via quarantine/manual review, not silent disappearance of known orders.

Local and exchange inventory are not mathematically guaranteed identical in every crash-without-order-id edge case, but for the audited production paths, divergence is detected, quarantined, and made observable rather than ignored.

---

ORDER INTEGRITY STATUS:  
**PRODUCTION READY**
