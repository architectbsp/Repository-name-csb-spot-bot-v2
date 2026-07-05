# DEVELOPMENT ROADMAP

Version: 1.0
Status: Active
Scope: CSB Spot Bot MVP

---

# Development Principles

Development always follows this order:

1. Terminal
2. Test
3. Documentation (if required)
4. Git Commit

No implementation is accepted without verification.

---

# Completed

Project initialization

Python virtual environment

Project structure

Configuration system

Logging infrastructure

Event Bus

Exchange abstraction

Retry Policy

Scheduler

Strategy skeleton

MarketData

Business Rules documentation

Architecture documentation

---

# Current Stage

Backend Development

Current Module:

MarketScanner

---

# Remaining Development Order

1. MarketScanner
2. WatchList
3. PositionManager
4. RiskManager
5. BotEngine Business Logic
6. Exchange Integration
7. UI Binding
8. End-to-End Testing
9. MVP Completion

---

# Working Rules

- One responsibility per module.
- One logical task at a time.
- Test every completed task.
- Update documentation when architecture or business rules change.
- Avoid duplicate implementations.

---

# Git Policy

One logical feature = One commit.

Commits must represent tested, working changes.

---

# Documentation Policy

The following documents are the project's permanent reference:

- docs/BUSINESS_RULES.md
- docs/ARCHITECTURE.md
- docs/DEVELOPMENT_ROADMAP.md
- docs/MVP_STATUS.md

Every new development session begins by reviewing these documents.
