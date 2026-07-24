# TASK-01 — Exchange API Configuration Isolation Fix

## Root cause

The API Settings dialog used **one shared set of TextFields** for all venues and, on exchange switch, reloaded values from `.env` via `_bind_exchange` **without first capturing** the in-progress field values into a per-exchange draft.

Consequences:
- Unsaved edits for exchange A were discarded (or still visible) when switching to B — appearing as shared/leaking UI state.
- There was no independent in-memory model per exchange; the UI itself was the only “state.”
- Persistence already used `BINANCE_*` / `BYBIT_*` keys, but the dialog lifecycle did not preserve drafts between switches or validate per venue.

## Fix applied

Introduced `ExchangeCredentialsSession` (`app/ui/api_config.py`):
- One **independent** `ExchangeCredentialDraft` instance per exchange (binance, bybit, okx, kraken, mexc).
- Switch: capture current fields → that exchange’s draft only → apply snapshot of the next exchange’s draft into the controls.
- Save: validate **only** the selected exchange; persist **only** that exchange’s `.env` keys (OKX alone writes passphrase).
- Load: reload all drafts from disk; UI shows the selected exchange only.
- Passphrase field visible only for OKX.

Dialog in `app/ui/app.py` rewritten to use the session (no trading/strategy/risk/OES changes).

## Files modified

| File | Change |
|------|--------|
| `app/ui/api_config.py` | **New** — isolated drafts + `.env` read/write |
| `app/ui/app.py` | API dialog uses session; removed shared bind helpers |
| `tests/test_api_config.py` | **New** — isolation / persist / validation tests |

## Verification results

| Check | Result |
|-------|--------|
| `compileall` (touched modules) | OK |
| Runtime isolation script | `RUNTIME_ISOLATION_OK` |
| `pytest tests/test_api_config.py` (+ related UI/settings) | 35 passed |
| Full regression `pytest -q` | **467 passed** |

Manual UI checklist (operator):
1. Open API Settings → enter Binance → switch Bybit → Binance values must not appear.
2. Enter Bybit → switch back to Binance → Binance draft still present.
3. Save each venue → close → reopen → each venue restores its own `.env` credentials.
4. Incomplete Binance validation must not mark Bybit/OKX/etc. as invalid.
