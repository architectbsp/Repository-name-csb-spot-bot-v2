# R6 — Security Hardening Report

**Sprint:** `R6_SECURITY_HARDENING`  
**Scope:** Secrets / credential exposure only  
**Behavior preservation:** Mandatory — no Strategy / RiskManager / OES trading logic / SQLite / recovery / UI / architecture changes  
**Date:** 2026-07-23

---

## 1. Security audit summary

Production audit focused on accidental leakage of exchange API keys/secrets, Telegram bot tokens, DB passwords, and signed request material through logs, exceptions, health payloads, Telegram alerts, and runtime sidecars.

**Findings addressed in code:**
- Dataclass `repr` could dump live `ExchangeSettings` / `TelegramSettings` credentials.
- Unredacted `str(exc)` from ccxt/httpx could embed signed URLs (`signature=`, `apiKey=`) into OES errors, worker health, scheduler `last_error`, exchange `last_error`, and Telegram detail lines.
- File/console logging had no secret scrubbing formatter.
- Memory log panel redacted Telegram tokens only.
- ccxt `verbose` dumps were not explicitly disabled.
- Runtime sidecars / WAL were not gitignored (commit footgun; contents had no API secrets).

**Already safe / unchanged:**
- API/Telegram secrets are env-sourced; not stored in SQLite `bot_settings`.
- Client-order / quarantine JSON sidecars contain order metadata only.
- Startup/shutdown logs do not dump settings objects.
- Telegram client already redacted bot URLs (now delegates to shared redactor).

---

## 2. Secrets inspected

| Secret | Storage | Exposure risk (pre-fix) | Mitigation |
|--------|---------|---------------------------|------------|
| Exchange `api_key` / `api_secret` / `passphrase` | Env → `ExchangeSettings` → ccxt | `repr`, ccxt error URLs, verbose headers | Masked `repr`; redaction; `verbose=False` |
| Telegram `bot_token` | Env → `TelegramSettings` | URL-in-exception; `repr` | Shared redaction + masked `repr` |
| DB password / `DATABASE_URL` | Env / optional `config.json` | Log of URL | Redact `user:pass@` in URLs; `config.json` gitignored |
| Signed REST `signature=` | Transient in ccxt errors | Logs / ExecutionResult.error / Telegram | Query-param redaction |

**Ops note (not a code change):** local `.env` should remain mode `600` and never be committed (already gitignored).

---

## 3. Redaction coverage

| Surface | Coverage |
|---------|----------|
| Root file + console logs | `RedactingFormatter` in `configure_logging` |
| UI memory log ring buffer | `redact_secrets` in `MemoryLogHandler.emit` |
| OES `ExecutionResult.error` | `safe_exc_message(exc)` |
| Worker / scheduler last_error | `safe_error_text(exc)` |
| BotEngine `runtime_health` + `worker.*` bus payloads | redacted messages |
| Exchange `state.last_error` | `safe_last_error(exc)` |
| Telegram ERROR / API disconnect details | `redact_secrets` |
| Telegram client logs | `redact_telegram_secrets` → shared `redact_secrets` |
| Settings `repr` | Masked credentials |

Shared helper: `app/core/security/redact.py` (`redact_secrets`, `safe_error_text`, `safe_exc_message`, `RedactingFormatter`).

---

## 4. Remaining exposure risks

### Critical

- None identified in application code paths covered above when redaction is active.

### Major

1. **Host / ops:** world-readable `.env` on a shared machine (filesystem ACL), not fixable in app code alone.
2. **`config.json` may still hold a DB password** if an operator writes one there; file is gitignored but can be copied. Prefer `DATABASE_URL` / `DB_PASSWORD` env.
3. **Debugger / interactive `pprint` of ccxt client object** can still show keys in a live REPL (outside production logging).

### Minor

1. Extremely unusual secret formats not matching redaction patterns could slip through (defense-in-depth patterns cover common ccxt/Telegram/DB cases).
2. Pre-R6 historical `logs/bot.log` files may still contain past unredacted lines — rotate/delete as ops hygiene.
3. UI startup dialog path (out of scope) may still interpolate a raw exception if BotEngine fails before logging config; production logging path is redacted.

---

## 5. Files changed

- `app/core/security/redact.py` (new)
- `app/core/security/__init__.py` (new)
- `app/core/logging_config.py`
- `app/core/config/settings.py`
- `app/core/services/telegram_client.py`
- `app/core/services/telegram_notifier.py`
- `app/core/services/telegram_command_handler.py`
- `app/core/services/memory_log.py`
- `app/core/services/order_execution.py` (error string redaction only)
- `app/core/worker.py`
- `app/core/scheduler/scheduler.py`
- `app/core/bot_engine.py` (health/bus message redaction only)
- `app/core/exchange/base.py` (`harden_ccxt_client`, `safe_last_error`)
- `app/core/exchange/{binance,bybit,okx,kraken,mexc,adapter}.py`
- `.gitignore` (WAL/SHM/sidecars/tmp)
- `tests/test_security_redact.py` (new)

**Not modified:** Strategy, RiskManager, SQLite schema/persistence logic, recovery logic, UI modules, trading decision paths.

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
431 passed, 2 warnings
```

---

## 8. Runtime result

```text
python main.py
remained alive ≥5s after launch (startup), then stopped
RUNTIME: OK
```

Logging uses redacting formatter; worker/health paths store redacted error text.

---

## 9. Final audit

### Critical Remaining Issues

- None in audited application logging / diagnostics / Telegram / health paths.

### Major Remaining Issues

1. Operator filesystem exposure of `.env` / optional `config.json` DB password.
2. Interactive debugging of live ccxt clients outside log redaction.

### Minor Remaining Issues

1. Legacy log files may predate redaction.
2. Exotic credential encodings outside pattern set.

---

## SECURITY STATUS:

**PRODUCTION READY**
