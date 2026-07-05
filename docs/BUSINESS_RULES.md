# BUSINESS_RULES

Version: 1.0
Status: Active
Scope: CSB Spot Bot MVP

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
                         Profit reaches +10%
                                 |
                                 v
                        +----------------+
                        |  BREAK_EVEN    |
                        +--------+-------+
                                 |
                     Stop moved to Entry Price
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

The position has reached at least +10% profit.

Entry

- Unrealized profit reaches +10%.

Responsibilities

- Move the stop loss to the entry price.
- This action is performed only once.

Exit

- Break-even stop triggered.
- Price continues upward.

Next State

TRAILING_ACTIVE

---

## TRAILING_ACTIVE

Description

Trailing stop becomes active after break-even.

Entry

- Break-even completed.

Responsibilities

- Keep the stop price 5% below the highest price reached after trailing activation.

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
5. Market Buy.
6. Initial Stop Loss = 5%.
7. Profit reaches +10%.
8. Stop moves to entry price.
9. Trailing stop becomes active with a distance of 5%.
10. Position closes.
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

## Position Size

- Every new position uses a maximum of 10% of the available account balance.

---

## Maximum Open Positions

- The bot may have at most 10 open positions simultaneously.
- If 10 positions are already open, no new signals are processed until a position is closed.

---

## Daily Loss Limit

- The daily realized loss limit is 20%.
- When this limit is reached, the bot must not open any new positions.
- Trading is suspended for 24 hours.
- Existing open positions continue to be managed normally.

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

# 9. Market Rules

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

# 10. System Rules

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

# 11. Forbidden Behaviors

The following behaviors are not allowed:

- Opening positions while a coin is in WATCH_FALLING.
- Opening more than 10 positions.
- Ignoring the daily loss limit.
- Bypassing the defined state machine.
- Skipping cooldown.
- Sending exchange orders directly from Strategy.
- Sending exchange orders directly from MarketScanner.
- Implementing business rules outside the defined business layer.

---

# 12. Document Maintenance

This document is the authoritative reference for the business behavior of the CSB Spot Bot.

Whenever a business rule changes:

1. Update this document.
2. Review the affected architecture.
3. Implement the change.
4. Test the implementation.
5. Commit the changes.

Business rules must never be changed in code before they are documented.
