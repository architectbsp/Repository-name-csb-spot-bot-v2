# BUSINESS_RULES

Version: 2.3
Status: Active
Scope: CSB Spot Bot MVP

Changelog (1.0 -> 2.0): hard stop moved from 5% to 10%; break-even and
trailing activation merged into a single 2% threshold; trailing distance
("callback rate") changed from 5% to 2.5%; position sizing changed from a
fixed 10% of balance to dynamic liquidity-based sizing (§8); daily loss
limit now resets at 00:00 UTC instead of a rolling 24h suspension (§8);
added Precision & Data Integrity rules (§9).

Changelog (2.0 -> 2.1): fixed Strategy never actually implementing Entry
Path A (a coin rising without a prior dip stayed in IDLE forever instead
of entering WATCH_RISING directly, §2); every strategy/risk parameter in
this document is now backed by a live Settings screen (persisted in
SQLite, applied without a restart) instead of any hardcoded value in
source, per §10 System Rules; Maximum Position Duration (§8) is now
actually enforced by a periodic scheduler job instead of being a
configured-but-unused value.

Changelog (2.1 -> 2.2): added the Order Execution Safety pipeline
(§8) -- duplicate-order protection, retry policy for transient/
insufficient-balance failures, bounded timeout, pending-order
reconciliation (poll -> cancel-with-retry), unknown-status handling and
symbol quarantine. Previously RiskManager called the exchange directly
with none of these protections, even though RetryPolicy/Timeout were
already wired in and unused.

Changelog (2.2 -> 2.3): added Position Lifecycle management (§8) --
Partial Take Profit / Scale Out (configurable, disabled by default),
Manual Close and Emergency Exit, all routed through the same
OrderExecutionService pipeline as every other exit; close_reason is now
stage-aware (HARD_STOP/BREAK_EVEN_STOP/TRAILING_STOP/MANUAL_CLOSE/
EMERGENCY_EXIT/MAX_DURATION) instead of a single generic "STOP_LOSS"
label; `position.pnl` on a fully-closed position now reflects the total
realized PnL across all partial exits plus the final exit, not just the
last chunk; added a lightweight additive SQLite schema-sync so a
database from a previous version never breaks the app on startup when a
Sprint adds a new persisted column.

---

# 1. Purpose

This document is the single source of truth for all business rules of the CSB Spot Bot.

Every trading decision, state transition, order execution and risk control must follow the rules defined here.

Business logic must never be implemented based on assumptions.

If a business rule changes, this document must be updated before the implementation.

---

# 2. Core Principles

The bot follows a single trading strategy.

There are not multiple strategies.

There are only two different entry paths into the same strategy.

Entry Path A

Price is already rising.

Entry Path B

Price is falling first and later reverses.

After the reversal begins, both paths become identical.

Every coin follows the same lifecycle.

No module may bypass this lifecycle.

---

# 3. Trading Scope

Current MVP supports:

- Spot trading only
- Market orders only
- Multiple exchange support
- One active strategy
- Maximum 10 simultaneous open positions

Not included:

- Futures
- Margin
- Leverage
- DCA
- Grid
- Portfolio optimization
- Multiple independent strategies

---

# 4. Trading Lifecycle

Every coin always belongs to exactly one state.

A coin cannot exist in multiple states simultaneously.

The lifecycle is defined as follows.---

# 5. Coin State Machine (FSM)

Every coin managed by the system follows the state machine below.

```text
                           +----------------+
                           |      IDLE      |
                           +-------+--------+
                                   |
                     Scanner detects movement
                                   |
                 +-----------------+-----------------+
                 |                                   |
          Price >= +2.5%                     Price <= -2.5%
                 |                                   |
                 v                                   v
        +----------------+                 +-----------------+
        | WATCH_RISING   |                 | WATCH_FALLING   |
        +--------+-------+                 +--------+--------+
                 |                                  |
                 |                     Continue tracking lows
                 |                                  |
                 |                     First upward movement
                 +---------------+------------------+
                                 |
                                 v
                        +----------------+
                        | WATCH_RISING   |
                        +--------+-------+
                                 |
                          Price reaches +6%
                                 |
                                 v
                        +----------------+
                        |  BUY_PENDING   |
                        +--------+-------+
                                 |
                         Market Order Filled
                                 |
                                 v
                        +----------------+
                        | POSITION_OPEN  |
                        +--------+-------+
                                 |
                         Profit reaches +2.0%
                                 |
                                 v
                        +----------------+
                        |  BREAK_EVEN    |
                        +--------+-------+
                                 |
             Stop moved to Entry Price (same instant)
                                 |
                                 v
                        +----------------+
                        | TRAILING_ACTIVE|
                        +--------+-------+
                                 |
                Stop / Trailing / Max Position Duration
                                 |
                                 v
                        +----------------+
                        |POSITION_CLOSED |
                        +--------+-------+
                                 |
                           Cooldown 4 Hours
                                 |
                                 v
                        +----------------+
                        |   COOLDOWN     |
                        +--------+-------+
                                 |
                           Cooldown Expired
                                 |
                                 v
                               IDLE
## BUY_PENDING

Description

A market buy order has been submitted.

Entry

- Buy condition (+6%) is satisfied.
- Market order is sent to the exchange.

Responsibilities

- Wait for the exchange execution result.
- Do not consider the position open until the exchange confirms execution.

Exit

- Order filled.

Next State

POSITION_OPEN

---

## POSITION_OPEN

Description

The position is active.

Entry

- Market order successfully filled.

Responsibilities

- Monitor stop loss.
- Monitor break-even condition.
- Monitor maximum position duration.
- Monitor daily risk restrictions.

Exit

- Stop loss triggered.
- Maximum position duration reached.
- Position closed for any valid reason.

---

## BREAK_EVEN

Description

The position has reached at least +2.0% profit.

Entry

- Unrealized profit reaches +2.0% (the same threshold that activates
  trailing -- break-even and trailing activation are one single event,
  not two separate stages).

Responsibilities

- Move the stop loss to the entry price (0 loss point) immediately, in
  the same tick that trailing activates.
- This action is performed only once.

Exit

- Break-even stop triggered.
- Price continues upward.

Next State

TRAILING_ACTIVE

---

## TRAILING_ACTIVE

Description

Trailing stop becomes active the instant profit reaches +2.0% (same
trigger as BREAK_EVEN; break-even and trailing activation happen
together).

Entry

- Unrealized profit reaches +2.0%.

Responsibilities

- Keep the stop price 2.5% ("callback rate") below the highest price
  reached since trailing activated, trailing it like a shadow. When the
  price reverses from the peak by 2.5%, the stop triggers and realizes
  the profit.

Exit

- Trailing stop triggered.
- Maximum position duration reached.

---

## POSITION_CLOSED

Description

The position is no longer active.

Possible Reasons

- Stop loss
- Break-even stop
- Trailing stop
- Maximum position duration

Next State

COOLDOWN

---

## COOLDOWN

Description

The coin cannot generate a new trading signal.

Entry

- Position closed.

Responsibilities

- Ignore all new entry opportunities for this coin.

Cooldown Duration

- 4 hours

Exit

- Cooldown timer expires.

Next State

IDLE

---

# 7. Trading Scenarios

## Scenario 1 - Rising Entry

1. Coin reaches +2.5%.
2. Coin enters WATCH_RISING.
3. Continue monitoring.
4. Coin reaches +6%.
5. Market Buy. Position size is computed dynamically (§8), not a fixed
   percentage of the account.
6. Initial Stop Loss (hard stop) = 10% below entry.
7. Profit reaches +2.0%.
8. Stop moves to entry price (break-even) and trailing activates in the
   same instant.
9. Trailing stop follows the highest price with a callback distance of
   2.5%.
10. Position closes when price reverses 2.5% from its peak (or the hard
    stop / max duration triggers first).
11. Coin enters 4-hour cooldown.

---

## Scenario 2 - Falling Then Reversal

1. Coin reaches -2.5%.
2. Coin enters WATCH_FALLING.
3. Continue monitoring while price declines.
4. The lowest price is continuously updated.
5. The first upward movement is detected.
6. Coin transitions to WATCH_RISING.
7. From this point forward, Scenario 1 applies without modification.
---

# 8. Risk Management

## Position Size - Dynamic Sizing & Liquidity Filter

Position size is **not** a fixed percentage of the treasury. It is
computed dynamically from two independent caps, and the **smaller** of
the two is always used:

1. **Balance cap**: at most 99.5% of the available account balance may
   be committed to a single trade. The remaining 0.5% headroom exists so
   commission and slippage never cause an order to be rejected for
   insufficient balance (never use 100% of the balance).
2. **Liquidity cap**: at most 0.1% ("binde 1") of the coin's 24-hour
   quote volume may be committed to a single trade, so the bot's own
   order can never meaningfully move the market or fail to fill cleanly.

```
position_size = min(balance * 99.5%, volume_24h * 0.1%)
```

- **Small treasury scenario** (e.g. $1,000): the liquidity cap is
  typically far larger than the balance cap, so `min()` resolves to the
  balance cap -> the bot commits 99.5% of the account to the single
  trade.
- **Large treasury scenario** (e.g. $100,000+): the liquidity cap is
  typically smaller than the balance cap, so `min()` resolves to the
  liquidity cap -> only the liquidity-safe amount is committed, and the
  remaining balance stays free for other opportunities (automatic risk
  distribution across positions).

---

## Maximum Open Positions

- The bot may have at most 10 open positions simultaneously.
- If 10 positions are already open, no new signals are processed until a position is closed.

---

## Daily Loss Limit

- A "trading day" starts the first time each UTC calendar day the bot
  observes the account balance; that balance becomes the day's starting
  treasury.
- The daily loss limit is 20% of the day's starting treasury, tracked
  against **realized** PnL only (closed positions), not unrealized
  drawdown on open positions.
- The instant realized loss reaches 20% of the day-start balance, the
  bot stops opening new positions ("kepenk kapatma" / circuit breaker).
- The breaker resets automatically at 00:00 UTC, when a new trading day
  (and a new starting treasury snapshot) begins.
- Existing open positions continue to be managed normally (stop
  loss/trailing/break-even keep working) even while the breaker is
  active; only new entries are blocked.

---

## Stop Loss / Trailing Stop Integration

- **Hard stop**: a fixed 10% stop loss below the entry price, active
  from the moment the position opens, as the last-resort safety valve
  against sudden crashes.
- **Trailing activation threshold**: the instant unrealized profit
  reaches +2.0%, trailing stop wakes up.
- **Break-even (risk reset)**: in the same instant trailing wakes up,
  the hard stop (waiting at -10%) is moved immediately to the entry
  price (the 0-loss point). Break-even and trailing activation are one
  single event sharing the same 2.0% threshold, not two separate stages.
- **Callback rate (trailing distance)**: once active, the stop trails
  2.5% behind the highest price reached, like a shadow; when price
  reverses from the peak by 2.5%, the stop triggers and realizes profit.

---

## Maximum Position Duration

- Default: 24 hours.
- This value is configurable from the user interface.
- When the maximum duration is reached, the position is closed using a market order.

---

## Insufficient Balance

If the exchange rejects an order because of insufficient balance:

- Retry after 1 minute.
- Retry a maximum of 3 times.
- If all retries fail, abandon the signal.

---

## Order Execution Safety

Every BUY and SELL submitted by RiskManager goes through
`OrderExecutionService` (`app/core/services/order_execution.py`), which
guarantees:

- **Duplicate order protection**: a symbol can never have two orders in
  flight at the same time. A second attempt while one is already
  submitting is rejected before it ever reaches the exchange.
- **Retry policy**: only transient network errors and insufficient-balance
  rejections are retried (see "Insufficient Balance" above for the exact
  numbers); any other exchange rejection (invalid order, generic exchange
  error) is never retried.
- **Timeout**: the blocking exchange call is bounded; a call that never
  returns cannot hang the bot forever.
- **Pending order reconciliation**: market orders are expected to fill
  immediately. If the exchange instead reports one as still open, it is
  polled a bounded number of times, then cancellation is attempted (with
  its own retries) before giving up.
- **Unknown order status handling**: a status this module does not
  recognize as filled/open/terminal is never guessed at (never silently
  treated as filled or as safe to ignore).
- **Quarantine**: a symbol left in an unreconciled or unknown-status state
  is quarantined -- no further order for that symbol is submitted until
  an operator manually verifies the real exchange state and clears it.
  This is surfaced as an `order.needs_manual_review` event.

---

## Position Lifecycle (Partial TP / Manual Close / Emergency Exit)

A position is no longer only ever fully opened once and fully closed
once. Three additional lifecycle actions exist, all implemented on
`RiskManager` and all routed through the exact same
`OrderExecutionService` pipeline (duplicate protection, retry, timeout,
reconciliation, quarantine) described above -- there is no separate
"shortcut" order path for any of them:

- **Partial Take Profit / Scale Out** (`check_partial_take_profit`,
  called on every price tick alongside break-even/trailing/stop-loss):
  once unrealized profit reaches the configurable
  `partial_tp_activation_percent` (0 = disabled, the default), sells
  `partial_tp_sell_percent`% of the position and leaves the remainder
  open under the exact same stop/break-even/trailing management as
  before. Fires at most once per position (`partial_exits_taken`
  guards this). The realized PnL from the partial sell is banked on the
  position (`realized_pnl`) and immediately counted against the daily
  loss/profit tracked for the circuit breaker.
- **Manual Close** (`close_position_manually(symbol)`): an
  operator-initiated full close, independent of any price trigger.
  Recorded with `close_reason="MANUAL_CLOSE"`.
- **Emergency Exit** (`emergency_exit_all()`): force-closes every open
  position immediately regardless of price or state -- an operator
  "panic button" distinct from the daily loss breaker (which only
  blocks *new* entries; this actively exits existing ones). Recorded
  with `close_reason="EMERGENCY_EXIT"`.
- **Close reason is stop-stage-aware**: when the ordinary stop-loss
  check closes a position, the recorded `close_reason` reflects which
  stop was actually active at the time --
  `HARD_STOP`/`BREAK_EVEN_STOP`/`TRAILING_STOP` -- instead of a single
  generic `STOP_LOSS` string, so a future Trade Journal (Sprint 5) can
  tell these apart. The Maximum Position Duration force-close is
  recorded as `MAX_DURATION`.

---

# 9. Precision & Data Integrity

## Reading and Displaying Exchange Data

- Prices and volumes read from an exchange's REST/WebSocket feed must
  never be rounded for display, logging, or internal comparisons. The
  value is kept at the precision the exchange sent it at (raw
  string / `Decimal`), not silently truncated by careless string
  formatting (e.g. `%.2f`) before it is used or logged.
- Log lines that print an exchange-sourced price must prefer the raw
  string the exchange sent over a reformatted float when one is
  available.

---

## Order Submission Armor

- Truncation (never rounding) to the exchange's `LOT_SIZE`/`stepSize`
  (quantity) and `PRICE_FILTER`/`tickSize` (price) limits happens
  **only** at the moment an order is actually submitted to the
  exchange -- never earlier in the pipeline. Rounding up a quantity
  could submit more than the wallet can afford; rounding a price could
  submit an invalid tick. Both must be truncated (floored), and the
  exchange-specific market metadata (`ccxt` market precision) for the
  exchange the order executes on is always the source of truth.

---

## Balance Usage Safety

- No order may ever be sized using 100% of the available balance. The
  hard ceiling is 99.5% of the balance, leaving headroom for commission
  and slippage so an order is never rejected for insufficient funds (see
  §8 Position Size).

---

# 10. Market Rules

## Volume Filter

- Only symbols with a 24-hour trading volume of at least 250,000 USD are eligible for scanning.

---

## Order Type

- All entries use Market Orders.

---

## Precision

- Price precision must exactly match the exchange.
- Quantity precision must exactly match the exchange.
- The application must never invent its own formatting rules.
- See §9 for exactly when truncation is (and is not) allowed to happen.

---

## Multi Exchange Support

The architecture must support multiple exchanges.

Supported exchanges for MVP architecture:

- Binance
- Bybit
- OKX
- Kraken
- MEXC

Only one exchange connection is active at a time.

---

# 11. System Rules

## Configuration

- No strategy or risk parameter referenced anywhere in this document
  (watch %, entry %, stop loss, break-even/trailing activation, trailing
  %, cooldown, max open positions, scan interval, min volume, dynamic
  sizing caps, max position duration, daily loss limit, partial take-
  profit activation/sell %) may be hardcoded in source.
- Every such parameter is defined once in `SETTINGS_SCHEMA`
  (`app/core/config/settings_store.py`), editable from the Settings
  screen, and persisted to SQLite (`bot_settings` table) so it survives
  restarts.
- Saving a change from the Settings screen applies it to the running bot
  immediately -- Strategy, WatchList, RiskManager and MarketScanner all
  read the shared, mutable configuration object fresh on every use, so
  no restart is required for a new value to take effect.

---

## Internet Connection

- If the internet connection is lost, the system retries every 10 seconds until connectivity is restored.

---

## Logging

The system logs every important business event.

Examples include:

- Scanner started
- Scanner finished
- Coin added to Watch List
- Coin removed from Watch List
- Buy signal detected
- Order submitted
- Order filled
- Stop Loss triggered
- Break-even activated
- Trailing activated
- Position closed
- Cooldown started
- Cooldown finished

The log screen provides:

- Real-time events
- Rolling 24-hour summary

---

# 12. Forbidden Behaviors

The following behaviors are not allowed:

- Opening positions while a coin is in WATCH_FALLING.
- Opening more than 10 positions.
- Ignoring the daily loss limit.
- Bypassing the defined state machine.
- Skipping cooldown.
- Sending exchange orders directly from Strategy.
- Sending exchange orders directly from MarketScanner.
- Implementing business rules outside the defined business layer.
- Rounding (instead of truncating) quantities/prices at order submission.
- Using more than 99.5% of the balance for a single order.
- Sizing a position above 0.1% of the coin's 24-hour volume.
- Hardcoding a strategy/risk parameter instead of adding it to
  `SETTINGS_SCHEMA` and reading it from the live configuration object.
- Submitting a second order for a symbol while one is already in flight.
- Retrying an exchange rejection that is not insufficient-balance.
- Treating an unrecognized order status as filled or as safe to ignore.
- Submitting a new order for a quarantined symbol without an operator
  first clearing the quarantine.
- Sending a manual close, emergency exit, or partial take-profit order
  through any path other than `OrderExecutionService` (e.g. calling the
  exchange manager directly, bypassing retry/reconciliation/quarantine).
- Firing automatic partial take-profit more than once for the same
  position.
- Scale Out reducing a position's quantity to zero (or below) while
  leaving it marked OPEN -- selling the entire remaining quantity must
  go through a full `close()`, never `scale_out()`.

---

# 13. Document Maintenance

This document is the authoritative reference for the business behavior of the CSB Spot Bot.

Whenever a business rule changes:

1. Update this document.
2. Review the affected architecture.
3. Implement the change.
4. Test the implementation.
5. Commit the changes.

Business rules must never be changed in code before they are documented.
