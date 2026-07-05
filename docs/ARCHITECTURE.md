# ARCHITECTURE

Version: 1.0
Status: Active
Scope: CSB Spot Bot MVP

---

# 1. Purpose

This document defines the software architecture of the CSB Spot Bot.

Business behavior is defined in BUSINESS_RULES.md.
This document defines how that behavior is implemented.

---

# 2. Design Principles

- Single Responsibility Principle
- State Driven Architecture
- Event Driven Communication
- Business Rules First
- Documentation First
- Exchange Agnostic Design
- No Circular Dependency

If an architectural decision changes, this document must be updated before implementation.

---

# 3. High-Level Architecture

UI
    │
    ▼
BotEngine
    │
    ├──────────────┬───────────────┐
    ▼              ▼               ▼
PositionManager  RiskManager   Strategy
                                      │
                                      ▼
                                 WatchList
                                      │
                                      ▼
                                MarketScanner
                                      │
                                      ▼
                                 MarketData
                                      │
                                      ▼
                                   Exchange

---

# 4. Layer Responsibilities

## UI

Responsible for:

- User interaction
- Displaying data
- Configuration
- Status visualization

Contains no business logic.

---

## BotEngine

Responsible for:

- Application lifecycle
- Module orchestration
- Trading workflow

Does not implement exchange-specific logic.

---

## PositionManager

Responsible for:

- Open positions
- Stop Loss
- Break-even
- Trailing Stop
- Maximum position duration
- Position closing

---

## RiskManager

Responsible for:

- Daily loss limit
- Maximum open positions
- Position sizing
- Balance validation
- Trade permission checks

---

## Strategy

Responsible only for generating entry signals.

Never:

- Sends orders
- Manages positions
- Performs risk validation

---

## WatchList

Responsible for:

- Coin tracking lifecycle
- Tracking state transitions
- Watch management
- Cooldown management

---

## MarketScanner

Responsible for:

- Scanning eligible symbols
- Applying volume filter
- Feeding WatchList

Contains no trading logic.

---

## MarketData

Responsible for:

- Market data retrieval
- Candle retrieval
- Ticker retrieval
- Precision retrieval
- Data normalization

---

## Exchange

Responsible for:

- Exchange API communication
- Orders
- Balances
- Positions

Contains no business rules.

---

# 5. Data Flow

Exchange
    ↓
MarketData
    ↓
MarketScanner
    ↓
WatchList
    ↓
Strategy
    ↓
RiskManager
    ↓
BotEngine
    ↓
Exchange

---

# 6. State Architecture

Three independent state groups exist.

## System State

- STARTING
- RUNNING
- PAUSED
- STOPPING
- STOPPED

Owned by BotEngine.

---

## Coin Tracking State

- IDLE
- WATCH_FALLING
- WATCH_RISING
- COOLDOWN

Owned by WatchList.

---

## Position State

- NONE
- BUY_PENDING
- OPEN
- BREAK_EVEN
- TRAILING
- CLOSED

Owned by PositionManager.

---

# 7. Dependency Rules

Allowed dependency direction:

UI
→ BotEngine
→ PositionManager / RiskManager / Strategy
→ WatchList
→ MarketScanner
→ MarketData
→ Exchange

Dependencies must always flow downward.

---

# 8. Forbidden Dependencies

Forbidden examples:

- UI → Exchange
- Strategy → Exchange
- Strategy → UI
- MarketScanner → BotEngine
- Exchange → Strategy
- Exchange → WatchList

No circular dependency is allowed.

---

# 9. Configuration

Runtime configuration is centralized in Settings.

Business modules must not read environment variables directly.

---

# 10. Logging

All modules use the shared logging infrastructure.

Each module logs only its own responsibilities.

---

# 11. Future Extension Rules

Future modules must:

- Respect dependency direction.
- Have a single responsibility.
- Integrate through BotEngine.
- Preserve state-driven architecture.
