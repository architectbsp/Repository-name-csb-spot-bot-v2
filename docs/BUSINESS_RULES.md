# BUSINESS_RULES

Version: 3.1
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
stage-aware (STOP_LOSS/BREAK_EVEN_STOP/TRAILING_STOP/MANUAL/
EMERGENCY/MAX_DURATION) via the `CloseReason` enum
label; `position.pnl` on a fully-closed position now reflects the total
realized PnL across all partial exits plus the final exit, not just the
last chunk; added a lightweight additive SQLite schema-sync so a
database from a previous version never breaks the app on startup when a
Sprint adds a new persisted column.

Changelog (2.3 -> 2.4): added the Trade Journal (§8) -- a permanent,
append-only record of every trade's full decision history (which entry
path, how long it was watched, how many times price rose/fell while
watching, which stop fired, realized PnL, duration), kept independently
of the `positions` table (whose row disappears the instant a position
closes). Strategy records the entry (it is the only module that knows
*why* a BUY happened); RiskManager records every partial and full exit
(it is the sole owner of every exit path).

Changelog (2.4 -> 2.5): added the Performance Analytics module (§8) --
Win Rate, Average Profit/Loss, Profit Factor, Expectancy, a simplified
per-trade Sharpe ratio, Maximum Drawdown and Recovery Factor, all
computed read-only from the Trade Journal's permanent closed-trade
history.

Changelog (2.5 -> 2.6): added Coin Charts (§8) -- clicking a coin in the
UI shows a TradingView-like chart (own price candles only, per §10's
exchange-isolation rule) with Entry / Stop / Take-Profit(trailing
activation) / Trailing-shadow overlay levels and Entry/Exit point
markers, sourced from the open Position or, once closed, the most
recent Trade Journal entry for that symbol. Read-only, drawn with Flet's
built-in canvas (no new charting dependency).

Changelog (2.6 -> 2.7): replaced every hardcoded mock panel on the
desktop dashboard with a live `DashboardSnapshot` (§8) rebuilt every
~2s from BotEngine modules (positions, watch/cooldown, trade journal,
daily PnL, quote balance, in-memory log tail). Ticker prices for the UI
come from an in-memory cache fed by `ticker.updated` (plus the last
MarketScanner result) -- the poll never REST-fetches every coin's price.

Changelog (2.7 -> 2.8): advanced Position Sizing (§8) -- hybrid mode
(default) takes the min of the existing balance/liquidity caps plus
risk-based, ATR-based and volatility-based caps (editable from the
Settings screen; falls back gracefully when OHLCV is unavailable).

Changelog (2.8 -> 2.9): simultaneous multi-exchange (§10) -- Binance /
Bybit / OKX / Kraken / MEXC may be connected at the same time via
`EXCHANGES=...` (legacy `EXCHANGE=` still works). Each venue keeps its
own API keys, balance, price stream, watch symbols and open positions.
Market identity is `(exchange, symbol)` (`market_key`); a ticker from
exchange A never sizes, opens or closes a position on exchange B.
Daily-loss treasury and dashboard quote balance are the sum across
enabled venues; position size still uses that venue's free balance only.

Changelog (2.9 -> 3.0): Telegram notifications (§8) -- optional Bot API
alerts for BUY / SELL / STOP / ERROR / API disconnect / internet
disconnect plus daily and weekly PnL summaries. Secrets stay in env
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`); a Telegram outage must never
block trading.

Changelog (3.0 -> 3.1): database backend abstraction (§11) -- the same
repository layer runs on SQLite (default), PostgreSQL or MariaDB/MySQL
via `DATABASE_URL` or `DB_BACKEND` + `DB_*` env vars. Schema sync is
dialect-aware; optional drivers live in `requirements-db.txt`.

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
always bounded by two hard safety caps, and the **smaller** is used:

1. **Balance cap**: at most 99.5% of the available account balance may
   be committed to a single trade. The remaining 0.5% headroom exists so
   commission and slippage never cause an order to be rejected for
   insufficient balance (never use 100% of the balance).
2. **Liquidity cap**: at most 0.1% ("binde 1") of the coin's 24-hour
   quote volume may be committed to a single trade, so the bot's own
   order can never meaningfully move the market or fail to fill cleanly.

```
safety_size = min(balance * 99.5%, volume_24h * 0.1%)
```

- **Small treasury scenario** (e.g. $1,000): the liquidity cap is
  typically far larger than the balance cap, so `min()` resolves to the
  balance cap.
- **Large treasury scenario** (e.g. $100,000+): the liquidity cap is
  typically smaller than the balance cap, so only the liquidity-safe
  amount is committed (automatic risk distribution across positions).

### Advanced Position Sizing (Risk / ATR / Volatility)

`position_sizing_mode` (Settings screen):

- **0 = Liquidity-only**: `position_size = safety_size` (legacy behaviour).
- **1 = Hybrid** (default): also take the min of any advanced caps that
  can be computed for the symbol. Missing OHLCV never blocks a trade --
  those caps are skipped and sizing falls back to `safety_size` (plus
  the risk-based cap, which needs no candles).

Advanced caps (all use Decimal math; all are Settings-editable):

1. **Risk-based**: size so a hard-stop hit loses at most
   `risk_per_trade_percent` of the treasury:
   `balance * risk_per_trade% / stop_loss%`.
2. **ATR-based**: fetch 1h candles from the active exchange only
   (isolation rule), compute ATR(`atr_period`), treat
   `ATR * atr_multiplier` as the stop distance:
   `balance * risk_per_trade% * price / (ATR * atr_multiplier)`.
3. **Volatility-based**: scale the balance cap by
   `volatility_target_percent / realized_vol%` (close-to-close sample
   stdev over `volatility_lookback` returns), clamped to
   `[0.25, 1.0]` so a quiet market never exceeds the balance cap and a
   spike never shrinks size below a quarter of it. Set
   `volatility_target_percent = 0` to disable this cap.

```
position_size = min(safety_size, risk_cap?, atr_cap?, vol_cap?)
```

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
  error) is never retried. Waits use exponential backoff
  (`delay * 2^(attempt-1)`, capped) for submit and cancel retries.
- **Timeout**: the blocking exchange call is bounded; a call that never
  returns cannot hang the bot forever.
- **Pending order timeout**: open/limit-style orders are polled for ~30s
  (configurable via `pending_timeout_seconds`), then cancellation is
  attempted (with its own retries) before giving up / quarantining.
- **Balance reconciliation** (`PositionReconciler`): on a scheduler
  interval, each OPEN local position's quantity is compared to the
  exchange free base-asset balance. A clear shortfall publishes
  `position.reconcile_mismatch` + `order.needs_manual_review` and
  quarantines that market (Unknown Order / DB drift).
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
  Recorded with `close_reason="MANUAL"`.
- **Emergency Exit** (`emergency_exit_all()`): force-closes every open
  position immediately regardless of price or state -- an operator
  "panic button" distinct from the daily loss breaker (which only
  blocks *new* entries; this actively exits existing ones). Recorded
  with `close_reason="EMERGENCY"`. UI: Open Positions → Emergency Exit.
- **Close reason (`CloseReason` enum)**: every exit records one of
  `STOP_LOSS` / `BREAK_EVEN_STOP` / `TRAILING_STOP` / `PARTIAL_TP` /
  `MANUAL` / `EMERGENCY` / `MAX_DURATION` / `MAX_DAILY_LOSS`. Hard stop
  uses `STOP_LOSS` (stage-aware extras distinguish break-even / trailing).
  `MAX_DAILY_LOSS` is reserved for a future force-close path; today the
  daily-loss breaker only blocks *new* entries. Maximum Position Duration
  force-close is recorded as `MAX_DURATION`.

---

## Trade Journal

Every trade (from the BUY that opens a position to the SELL that finally
closes it) gets a permanent `trade_journal` row (`TradeJournalEntry` /
`app/core/services/trade_journal.py`), independent of the `positions`
table -- closing a position deletes its `positions` row, but its journal
entry is never deleted.

- **Recorded at entry** (by Strategy, the instant a BUY fills and the
  position is promoted to `POSITION_OPEN`): symbol, exchange, entry
  price/quantity, `entry_reason` (`PATH_A_DIRECT_RISE` or
  `PATH_B_DIP_RECOVERY` -- see §2), when the watch cycle started, how
  many minutes it was watched before the BUY, and how many times a new
  high (`rise_events`) or new low (`fall_events`, Path B only) was
  recorded while watching.
- **Recorded on every partial exit** (by RiskManager's Scale Out /
  Partial Take Profit): quantity sold, exit price, realized PnL, running
  totals (`partial_exit_count`, `partial_exit_pnl`). The trade stays
  `OPEN` in the journal.
- **Recorded on final exit** (by RiskManager, for every full-close path --
  ordinary stop-loss, Manual Close, Emergency Exit, or Maximum Position
  Duration): exit price, `exit_reason` (the same stage-aware value
  recorded as `close_reason` above), total realized PnL/PnL%, and how
  many minutes the trade was held from entry to exit. The trade is then
  marked `CLOSED`.

---

## Performance Analytics

`PerformanceAnalytics` (`app/core/services/performance_analytics.py`) is
a read-only module that measures the bot's own trading performance from
every `CLOSED` Trade Journal entry. It never touches a position, order,
or risk state -- only summarizes what already happened.

- **Win Rate**: percentage of closed trades with `pnl > 0`.
- **Average Profit / Average Loss**: mean `pnl` of winning trades and of
  losing trades, respectively.
- **Profit Factor**: gross profit / gross loss. Undefined (`None`) with
  zero closed trades; `+infinity` when there have been wins and zero
  losses so far (a "perfect" record, not literally infinite money).
- **Expectancy**: total realized PnL / number of closed trades -- the
  expected PnL of the "average" trade.
- **Sharpe ratio**: a simplified, non-annualized ratio (mean / stdev of
  each trade's `pnl_percent`, scaled by sqrt(N)) appropriate for a
  trade-by-trade sample rather than a time-series of periodic returns.
  `None` with fewer than 2 usable trades or zero-variance returns.
- **Maximum Drawdown**: the largest peak-to-trough drop of the
  cumulative realized-PnL equity curve built by walking closed trades in
  chronological order (by exit time).
- **Recovery Factor**: total realized PnL / maximum drawdown -- how many
  times over the worst drawdown has been recovered by total profit.

## Coin Charts

`ChartService` (`app/core/services/chart_service.py`) assembles a
read-only, per-symbol chart: recent OHLCV candles fetched from that
symbol's own active exchange only (via `ExchangeManager.fetch_ohlcv`,
never mixed with another exchange's data -- see §10) plus overlay levels
for whichever trade the symbol currently has:

- If there is an **open Position**, the overlay uses its live
  `entry_price`, `stop_price`, `stop_stage` and `highest_price`
  (trailing shadow reference), plus a Take-Profit/trailing-activation
  target computed from `entry_price * (1 + trailing_activation_percent)`.
- Otherwise, it falls back to the **most recently closed Trade Journal
  entry** for that symbol (entry/exit price, time and reason).
- With no trade history at all, only the raw price line is drawn.

`app/ui/components/coin_chart.py` renders this into a TradingView-like
line chart (price line + dashed Entry/Stop/TP/Trailing level lines +
Entry/Exit point markers) using Flet's built-in `flet.canvas` -- no
external charting/plotting dependency was added, consistent with the
minimal pinned-dependency policy (§10/B29). Clicking a coin row in the
coin table or an open-position card opens this chart in a modal dialog.

## Live Dashboard

`DashboardService` (`app/core/services/dashboard_service.py`) assembles
a single read-only `DashboardSnapshot` for the Flet UI. Panels never
poke PositionManager / WatchList / RiskManager directly -- they only
render this DTO.

Snapshot contents:

- **Account / top bar**: enabled exchange name(s), testnet vs live,
  summed quote balance across venues, bot running flag, API connection
  status (`ConnectionStatus.CONNECTED` on any enabled exchange).
- **Cards**: portfolio balance, signed daily realized PnL % (from
  RiskManager's UTC day-start balance + realized PnL today), open
  position count, active watch-signal count.
- **Coin table / open positions**: watch-list coins + open positions,
  enriched with last-known ticker (raw price string preferred, §9).
  Unrealized PnL % = `(last - entry) / entry * 100`. Spot side is
  always LONG.
- **Watch list / cooldown**: coins in `WATCH_FALLING` /
  `WATCH_RISING` / `BUY_PENDING`, and coins in `COOLDOWN` with
  remaining time.
- **Trade history / 24h report**: closed Trade Journal entries
  (history panel) and a 24-hour window aggregate (wins/losses/net PnL).
- **Live log**: tail of an in-memory ring buffer (`MemoryLogHandler`)
  attached to the root logger -- no disk re-read on every poll.

Refresh model: a background Flet `page.run_thread` poll (~2s) rebuilds
the Dashboard view while the user is on that screen. High-frequency
`ticker.updated` events only update the DashboardService ticker cache
(never mutate UI controls from the WebSocket thread). Quote balance is
the only REST call on a poll tick and is best-effort (failures leave
the previous/None value).

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

The architecture must support multiple exchanges connected
**simultaneously** (Sprint 18).

Supported exchanges for MVP architecture:

- Binance
- Bybit
- OKX
- Kraken
- MEXC

Configuration:

- Preferred: `EXCHANGES=binance,bybit,okx` plus per-venue credentials
  (`BINANCE_API_KEY` / `BINANCE_API_SECRET`, `BYBIT_...`,
  `OKX_...` + `OKX_PASSPHRASE`, …).
- Legacy single-exchange: `EXCHANGE=binance` + `EXCHANGE_API_KEY` /
  `EXCHANGE_API_SECRET` (still supported when `EXCHANGES` is unset).

Isolation rules (non-negotiable):

- Every market-facing key is `(exchange, symbol)` via `market_key`
  (WatchList, PositionManager, OrderExecution quarantine, dashboard
  ticker cache, persisted `positions.position_key`).
- Price ticks, OHLCV candles and order placement for a symbol on
  exchange A must never act on the same symbol on exchange B.
- Each venue has its own WebSocket price stream subscription list.
- Position size is computed from **that venue's** free quote balance;
  the daily-loss circuit breaker uses the **sum** of free quote
  balances across every enabled venue as the shared treasury snapshot.
- `max_open_positions` remains a global cap across all venues (one
  strategy, one risk budget).

---

## Telegram Notifications

`TelegramNotifier` (`app/core/services/telegram_notifier.py`) is an
optional, read-only operator channel. It never places orders and never
mutates Position / Risk / WatchList state. Send failures are logged and
ignored so a Telegram outage cannot interrupt trading.

Configuration (environment only -- never stored in SQLite):

- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (required to enable)
- `TELEGRAM_ENABLED` (optional explicit on/off; defaults to on when both
  credentials are present)
- `TELEGRAM_DAILY_SUMMARY_HOUR` (UTC hour, default `0`)
- `TELEGRAM_WEEKLY_SUMMARY_WEEKDAY` (Monday=0 … Sunday=6, default `0`)

Alert types:

| Event | Source |
|---|---|
| **BUY** | `position.opened` after a filled market buy |
| **SELL** | `position.closed` / `position.partial_exit` (non-stop reasons) |
| **STOP** | `position.closed` with `STOP_LOSS` / `BREAK_EVEN_STOP` / `TRAILING_STOP` |
| **ERROR** | `order.needs_manual_review`, `risk.daily_loss_limit` |
| **API Disconnect** | websocket close/error or exchange `ConnectionStatus` flip |
| **Internet Disconnect** | periodic probe of `api.telegram.org` (state-change only) |
| **Daily / Weekly Summary** | closed-trade PnL window from Trade Journal |

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
  screen, and persisted to the configured database (`bot_settings`
  table -- SQLite by default, optionally PostgreSQL or MariaDB) so it
  survives restarts.
- Saving a change from the Settings screen applies it to the running bot
  immediately -- Strategy, WatchList, RiskManager and MarketScanner all
  read the shared, mutable configuration object fresh on every use, so
  no restart is required for a new value to take effect.

---

## Database Backend

Persistence is accessed only through repository protocols
(`SettingsRepository`, `PositionRepository`, `TradeJournalRepository`).
Callers must not open raw SQL connections or branch on dialect.

Supported backends (Sprint 13):

| Backend | How to select |
|---|---|
| **SQLite** (default) | unset / `DB_BACKEND=sqlite` / `DB_PATH=...` |
| **PostgreSQL** | `DB_BACKEND=postgresql` + `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`, or a full `DATABASE_URL` |
| **MariaDB / MySQL** | `DB_BACKEND=mariadb` (or `mysql`) + the same `DB_*` fields, or `DATABASE_URL` |

`DATABASE_URL` always wins when set. Optional drivers:
`pip install -r requirements-db.txt` (`psycopg`, `PyMySQL`). Schema
evolution uses the dialect-aware `sync_schema()` helper (no Alembic).

---

## Internet Connection

- If the internet connection is lost, the system retries every 10 seconds until connectivity is restored.
- When Telegram is enabled, an internet / Telegram-API outage also emits a
  one-shot **INTERNET DISCONNECT** alert (and a reconnect alert when the
  probe succeeds again). Trading continues independently of Telegram.

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
