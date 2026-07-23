# FINAL PRODUCTION AUDIT

**Audit type:** Independent Principal Software Architect review  
**Subject:** `csb-spot-bot-v2` current HEAD (R1–R7.5 complete)  
**Mode:** Read-only — no code modified, no redesign proposed beyond verdict impact  
**Assumption:** Real capital at risk; unattended 24/7 is the bar unless conditions say otherwise  
**Date:** 2026-07-23

---

## 1. Executive Summary

This codebase has been systematically hardened across concurrency, worker reliability, SQLite durability, order integrity, ClientOrderId idempotency, restart recovery, secret redaction, in-process health aggregation, and chaos fault injection. The execution path is disciplined: RiskManager submits only through `OrderExecutionService`; ambiguous outcomes quarantine; fills can remain `AWAITING_LOCAL` until local persistence confirms; active ClientOrderIds are recovered on startup/reconnect; secrets are scrubbed from logs/diagnostics; operators can call `health_snapshot()`.

What it is **not**: a headless, externally supervised production service with wallet-wide orphan detection and push-based ops alerting. It is a **desktop Flet trading application** with strong in-process safety rails. For carefully supervised live trading on testnet/small capital with explicit ops discipline, it can be production-worthy. For unsupervised 24/7 real-money running without conditions, it is not yet at that bar.

---

## 2. Production Readiness Score (0–100)

**76 / 100**

| Band | Interpretation |
|------|----------------|
| 90–100 | Unattended real-money service grade |
| 75–89 | Production-capable with explicit conditions |
| 60–74 | Paper / supervised only |
| <60 | Not ready |

**76** reflects solid R1–R7.5 engineering quality and chaos evidence, discounted for desktop process model, quarantine-scoped orphans, sync EventBus on WS threads, and operator-dependent recovery unlocks.

---

## 3. Critical Remaining Issues

**None identified** that imply silent, automatic double-spend or silent inventory erasure on the covered OrderExecution → ClientOrderId → AWAITING_LOCAL → recover_inflight path when the ClientOrderId sidecar is enabled and venues honor client order ids.

(If Critical is defined as “can lose money without any signal,” the closest candidates are treated as **Major** below because quarantine/observability usually fires on the hardened paths; unmanaged wallet inventory outside quarantine remains a real but scoped gap.)

---

## 4. Major Remaining Issues

1. **Orphan inventory detection is quarantine-scoped** — free base on markets never quarantined is not scanned; unmanaged inventory can exist without `ORPHAN_INVENTORY` events.
2. **No external health endpoint** — `health_snapshot()` is in-process only; no HTTP/liveness probe for supervisors, systemd, or remote ops.
3. **Desktop / UI process model** — `main.py` runs Flet; process lifetime is tied to a GUI app, not a supervised headless worker.
4. **Synchronous EventBus on WebSocket threads** — ticker handlers (including strategy/risk) run on the stream callback thread; a slow/blocking handler can stall market data and cascade into stale decisions.
5. **`clear_quarantine` is operator trust** — clears quarantine and active ClientOrderId binding without exchange verification; incorrect unlock can allow a new logical order over unresolved venue state.
6. **Venue ClientOrderId recovery variance** — if fetch-by-client-id / open-order scan fails, system quarantines (safe) but requires human resolution; not fully automatic.
7. **Trading mode / testnet defaults are ops footguns** — mode can default to REAL while testnet defaults true; misconfiguration risk for first live deploy if env is incomplete.
8. **Live `Position` mutation after `get()`** — RiskManager mutates stop/highest on the live object outside PositionManager’s lock for the mutation duration; R1 residual race under concurrent readers.

---

## 5. Minor Remaining Issues

1. Journal ENTRY can lag position persist (kill between `add` and journal → position without journal row).
2. Trailing / break-even / stop updates may lose the last tick if process dies before end-of-`update_position` persist.
3. Multi-venue health uses OR “any connected”; one dead venue can be masked unless `venues[]` is inspected.
4. EventBus handler errors are counted/logged but do not quarantine markets.
5. Scheduler delay detection requires calling `health_snapshot()` (no push alert).
6. Telegram emergency kill switch exists only when Telegram is configured.
7. Chaos “kill -9” was simulated via durable sidecars, not a literal OS kill in CI.
8. Stale MVP documentation may understate current hardening state (ops confusion risk).

---

## 6. Technical Debt (safe to defer)

- Immortal SQLAlchemy repository sessions (R3 residual) under single-process desktop use.
- Client-order / quarantine JSON registry growth without pruning.
- Paper vs live adapter complexity unrelated to safety rails.
- Dashboard/Telegram not yet rendering the full health snapshot (observability exists in-process).
- Immortal docs drift (`MVP_STATUS.md` vs R-sprint reality).
- SharedMarketOrderGate / multi-strategy edge cases beyond single-pipeline OES in-flight guards.

---

## 7. Strengths

- **OrderExecutionService as single submission gate** with in-flight, quarantine, pending poll, cancel verify, unknown-status handling.
- **Durable ClientOrderId** with retry reuse, DuplicateOrderId recovery, and restart sidecar.
- **AWAITING_LOCAL + local persist confirm** closes the classic fill-before-position crash window.
- **Startup/reconnect `recover_inflight_orders`** makes ambiguity observable without waiting for a new signal.
- **SQLite WAL + busy_timeout + quick_check + commit rollback** suitable for long-running local durability.
- **Worker/scheduler failures are visible** (no silent `except: pass` on the hardened path).
- **Secret redaction** across logs, health, OES errors, Telegram details, settings `repr`.
- **`health_snapshot()`** answers alive/degraded/worker/exchange/WS/scheduler/recovery/DB questions in one call.
- **Chaos suite (21+) + ~457 pytest cases** provide regression evidence for the hardening claims.
- **Spot-only / market-order guards** reduce accidental futures/margin exposure.

---

## 8. Weaknesses

- Not a supervised headless trading service; GUI-coupled lifetime.
- Inventory truth is “local positions + quarantined markets,” not full exchange wallet reconciliation.
- Concurrency model still allows WS-thread business logic and unlocked Position field races.
- Recovery convergence often ends in **quarantine + human**, not automatic position attach.
- External ops tooling (HTTP health, paging, remote kill without Telegram) is incomplete.
- Defaults and docs can mislead a rushed first live deploy.

---

## 9. Operational Recommendations

1. Run first capital **supervised** (human online), not unattended.
2. Prefer **testnet / paper** until ops runbooks for quarantine clear and reconnect are rehearsed.
3. Explicitly set `TRADING_MODE`, `EXCHANGE_TESTNET`, and exchange credentials; verify mode banner before enabling.
4. Configure Telegram with `/emergency` for remote freeze+exit.
5. Ensure ClientOrderId / quarantine sidecars are on durable disk (not `:memory:`).
6. Lock down `.env` (`chmod 600`); never commit sidecars or DB files.
7. On every quarantine: verify exchange orders/balances **before** `clear_quarantine`.
8. Periodically call/inspect `health_snapshot()`; treat `degraded` / `recovery.attention` as page-worthy.
9. Keep max position size and daily loss limits conservative for first live weeks.
10. After any crash/restart: confirm recover_inflight ran, reconciler ran, and no unexpected free base on traded symbols.

---

## 10. Conditions before first live capital

1. **Explicit REAL + intended venue** (testnet vs live) confirmed in UI/logs.
2. **Telegram emergency path tested** end-to-end on the target account.
3. **Sidecar paths writable** next to SQLite; restart drill completed once.
4. **Quarantine clear runbook** written and practiced (exchange check first).
5. **Position sizing / daily loss / max opens** set to loss-tolerant limits.
6. **Human on-call** for at least the first continuous session (not 24/7 alone).
7. **Manual wallet check** of free bases for symbols the bot may trade (compensate for quarantine-scoped orphans).
8. **No reliance on HTTP health** — use process supervision appropriate to a desktop app, or accept that GUI exit stops trading.

Until these are met: paper/testnet only.

---

## 11. Final Verdict

**PRODUCTION READY WITH CONDITIONS**

---

## Most Important Question

**If this were your own money, would you allow this bot to trade unattended 24/7?**

### YES WITH CONDITIONS

**Technical justification:**

I would **not** let it run unattended 24/7 on meaningful capital in its current form: desktop process model, no external health probe, quarantine-scoped orphan detection, WS-thread synchronous fan-out, and operator-trusted quarantine clears are incompatible with “set and forget” real-money operation.

I **would** allow it to trade **my own money in small size** under the conditions in §10: supervised sessions, confirmed mode/testnet, Telegram emergency, restart/quarantine runbooks, conservative limits, and manual wallet checks — because the execution/idempotency/recovery/security rails materially reduce silent double-order and silent fill-loss failure modes that previously blocked any live consideration.

Unattended 24/7 without those conditions: **No.**
