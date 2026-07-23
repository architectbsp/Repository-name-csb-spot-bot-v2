# R5 — Client Order Idempotency Report

**Sprint:** `R5_CLIENT_ORDER_IDEMPOTENCY`  
**Scope:** Execution idempotency only (ClientOrderId)  
**Behavior preservation:** Mandatory — no Strategy / RiskManager / UI / architecture redesign  
**Date:** 2026-07-23

---

## 1. Idempotency strategy

Every logical BUY/SELL through `OrderExecutionService` receives one durable **ClientOrderId** (`csb` + hex, ≤32 chars) **before** the venue submit:

1. **Allocate / reuse** via `ClientOrderRegistry.begin_logical_trade()` keyed by `market_key(exchange, symbol)`.
2. **Persist PENDING** to a JSON sidecar (`*.client_orders.json` next to SQLite) before `execute_trade`.
3. **Attach** as `TradeRequest.client_order_id` (OES-only; RiskManager unchanged) → ccxt `params={"clientOrderId": ...}` on all venue `create_market_*_order` paths (paper included).
4. **Reuse** the same id across in-process REST retries (`NetworkError` / `InsufficientFunds` policy).
5. **Recover** on `TimeoutError`, exhausted `NetworkError`, or `DuplicateOrderId` via `fetch_order_by_client_id` (unified fetch + open/closed order scan).
6. **Restart:** active PENDING/SUBMITTED/AMBIGUOUS records reload from the sidecar; the next logical attempt for that market reuses the same id and prefers recovery before a new submit.
7. **Operator `clear_quarantine`** also clears the active ClientOrderId binding so a verified market can start a new logical id.

---

## 2. Retry analysis

| Scenario | Behavior |
|----------|----------|
| BUY / SELL REST retry (`NetworkError`) | Same `client_order_id` on every attempt |
| Exchange accepts then client sees network loss | Retry may raise `DuplicateOrderId` → recover by client id → `FILLED` / classify |
| Insufficient funds retries | Same id; on final reject → mark FAILED, release market slot |
| Invalid / exchange reject | No retry of rejection; mark FAILED |

---

## 3. Restart analysis

| Scenario | Behavior |
|----------|----------|
| Crash / kill after PENDING persist, before response | Sidecar keeps active id; restart reuses id; recover-or-resubmit same id |
| Timeout after venue fill, no `order_id` in response | Recover via client id when venue supports lookup; else AMBIGUOUS + quarantine |
| Restart after successful response + COMPLETED | Active slot cleared; next trade gets a new id |
| Restart after AMBIGUOUS + quarantine | Quarantine blocks new submits; clear_quarantine releases both quarantine and active cid |

---

## 4. Audit matrix (VERIFY)

| Case | Status |
|------|--------|
| BUY retry | Covered (same cid) |
| SELL retry | Covered (same cid) |
| Network timeout | Recover if possible; else AMBIGUOUS + quarantine |
| Exchange timeout | Same as network timeout path |
| Restart before response | Active cid reuse + recover/resubmit |
| Restart after response | COMPLETED; new logical id next |
| Duplicate REST retry | `DuplicateOrderId` → recover |
| Duplicate WS response | Out of R5 scope (no strategy change); submit path remains single cid per logical trade |

---

## 5. Remaining risks

### Critical

- None identified for duplicate **submit** of the same logical ClientOrderId when the venue honors `clientOrderId` / `DuplicateOrderId`.

### Major

1. **Venue support variance** — some exchanges may not reliably fetch by clientOrderId or may map the unified param differently; recovery then falls back to open/closed scans (best-effort).
2. **Crash after venue fill but before PENDING persist** — theoretically empty window if process dies between “decide to trade” and `begin_logical_trade`; OES always persists before submit, so this window is before any exchange call.
3. **Operator clear_quarantine without exchange verification** — can allow a new ClientOrderId while an old venue order still exists (same as R4 operator responsibility).

### Minor

1. Registry JSON retains historical COMPLETED/FAILED records (no pruning yet).
2. Paper duplicate raises `DuplicateOrderId` (OES recovers); live venues must map similarly via ccxt.
3. Duplicate WebSocket strategy ticks remain CPU-level noise; BUY still gated by position / in-flight / quarantine / cid reuse.

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
420 passed, 2 warnings
```

New coverage: `tests/test_client_order_idempotency.py` (retry reuse, DuplicateOrderId recovery, timeout recover, ambiguous persist, restart reuse, sell retry, registry reuse).

---

## 8. Runtime result

```text
python main.py
remained alive ≥5s after launch, then stopped
RUNTIME: OK
```

---

## 9. Files touched (execution path only)

- `app/core/services/client_order_registry.py` (new)
- `app/core/services/order_execution.py`
- `app/core/trading/models.py` (`client_order_id` optional field)
- `app/core/exchange/base.py` / `manager.py` / `budgeted.py` / venues / `adapter.py`
- `app/core/bot_engine.py` (sidecar path wiring)
- Tests: `test_client_order_idempotency.py`, `test_spot_guard.py`

**Not changed:** Strategy, RiskManager logic, UI, SQLite schema.

---

## 10. Final audit

### Critical Remaining Issues

- None for ClientOrderId duplicate-submit protection on the OES path.

### Major Remaining Issues

1. Exchange-specific clientOrderId fetch reliability (best-effort scan fallback).
2. Operator `clear_quarantine` can still unlock a market while a live orphan order exists if not verified.

### Minor Remaining Issues

1. Client-order registry growth without pruning.
2. WS duplicate tick CPU work (pre-existing).

---

## CLIENT ORDER IDEMPOTENCY STATUS:

**PRODUCTION READY**
