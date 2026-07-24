# TASK-02 — Exchange Selection & Activation Repair

## Root cause

1. **Top-bar exchange chips were non-interactive** — `_exchange()` rendered plain `Container`s with no `on_click` / `ink`.
2. **`build_top_bar` had no selection callback** — unlike API/Settings actions.
3. **No selectable active-exchange state** — `ExchangeManager.active_exchange_type()` always returned the first enabled venue; highlight used “all enabled” instead of a single active venue.

## Fix applied

- `ExchangeManager`: `set_active_exchange_type` / `selected_exchange_type`; `active_exchange_type()` prefers the selection when registered.
- `BotEngine.select_active_exchange` + startup seed from `config.exchange`.
- `DashboardSnapshot.active_exchange` + dashboard status/balance follow the selection.
- Top-bar chips clickable; only the active venue is highlighted; status box shows the active name.
- UI callback loads that venue’s API credentials from `.env`, persists `EXCHANGE=`, rebuilds the view immediately (including dashboard poll path).

## Files modified

| File | Change |
|------|--------|
| `app/core/exchange/manager.py` | Active selection state |
| `app/core/bot_engine.py` | `select_active_exchange` + startup seed |
| `app/core/domain/dashboard.py` | `active_exchange` field |
| `app/core/services/dashboard_service.py` | Snapshot + balance use active venue |
| `app/ui/components/top_bar.py` | Clickable chips + active highlight |
| `app/ui/components/content.py` | Pass `on_exchange_select` |
| `app/ui/app.py` | Wire selection + persist + refresh |
| `tests/test_exchange_selection.py` | New coverage |
| `TASK02_EXCHANGE_SELECTION_REPORT.md` | This report |

## Verification

| Check | Result |
|-------|--------|
| compileall | OK |
| Runtime cycle all venues | `RUNTIME_SELECTION_OK` |
| Full pytest | **470 passed** |
