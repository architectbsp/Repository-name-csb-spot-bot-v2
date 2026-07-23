# DEPENDENCY AUDIT

**Mode:** Read-only (no code modified)  
**Date:** 2026-07-23  
**Sources:** `requirements.txt`, `requirements-dev.txt`, `requirements-db.txt`, `pyproject.toml`, `app/` + `tests/` imports, local `.venv` (`pip check`), OSV.dev queries for pinned/transitive packages  
**Python target:** `>=3.12` (`pyproject.toml`)

---

## Executive summary

Runtime dependency surface is **small and mostly intentional**. Exact pins in `requirements.txt` are enforced by tests. `pip check` reports **no broken requirements**. OSV reports **no known vulnerabilities** for the pinned runtime set and key transitive packages checked today.

Main findings: **`msgpack` is declared but never imported** (redundant explicit pin of a Flet transitive), **`flet-desktop` is required but not imported** (correct companion package), optional DB drivers are **intentionally absent** from the default install, and **dev/db requirement files use unpinned ranges** (reproducibility risk, not a resolver conflict today).

---

## Inventory

### Runtime — `requirements.txt` (exact pins)

| Package | Pin | Direct import in `app/` | Role |
|---------|-----|-------------------------|------|
| `flet` | `0.85.3` | Yes (`import flet`) | Desktop UI |
| `flet-desktop` | `0.85.3` | No (companion) | Flet native desktop runtime |
| `httpx` | `0.28.1` | Yes | Telegram HTTP client (+ also required by Flet) |
| `msgpack` | `1.2.1` | **No** | Transitive of Flet; also pinned top-level |
| `ccxt` | `4.5.64` | Yes | Exchange API |
| `python-dotenv` | `1.2.2` | Yes (`dotenv`) | `.env` loading |
| `websocket-client` | `1.9.0` | Yes (`import websocket`) | Exchange price streams |
| `SQLAlchemy` | `2.0.51` | Yes | Persistence |

### Dev — `requirements-dev.txt` (minimum ranges)

| Package | Spec | Used by |
|---------|------|---------|
| `pytest` | `>=8.4` | tests |
| `pytest-cov` | `>=7.0` | CI coverage |
| `ruff` | `>=0.9` | lint |
| `mypy` | `>=1.14` | typecheck |

### Optional DB — `requirements-db.txt` (minimum ranges)

| Package | Spec | Used when |
|---------|------|-----------|
| `psycopg[binary]` | `>=3.2` | PostgreSQL backend |
| `PyMySQL` | `>=1.1` | MySQL/MariaDB backend |

Default path is SQLite (stdlib + SQLAlchemy) — these are **not** required for normal launch.

### `pyproject.toml`

Declares `requires-python` and tool config only. **No `[project.dependencies]`** — install truth lives in requirements files (single practical source: `requirements*.txt`).

---

## 1. Unused packages

| Package | Verdict | Notes |
|---------|---------|-------|
| **`msgpack`** | **Unused as a direct app dependency** | Zero `import msgpack` in `app/` or `tests/`. Still pulled by `flet` (`msgpack>=1.1.0`). Top-level pin is **redundant but harmless** (locks transitive version). |
| Everything else in `requirements.txt` | **Used** | Direct import or required desktop companion (`flet-desktop`). |

**Not classified as unused**
- `flet-desktop` — not imported in Python, but required for `ft.run` desktop mode.
- `psycopg` / `PyMySQL` — optional; unused only if you stay on SQLite (by design).
- Local venv extras (`radon`, `vulture`, etc.) — **not declared** in requirements; environment pollution, not project unused deps.

---

## 2. Missing packages

| Gap | Severity | Notes |
|-----|----------|-------|
| No missing **required** runtime imports | — | All third-party imports in `app/` map to declared packages. |
| **`psycopg` / `PyMySQL` not in default install** | Low (conditional) | Missing only if operator configures Postgres/MySQL without `pip install -r requirements-db.txt`. Documented in `.env.example` / docs. |
| Type stubs (`types-*`) | Low | `mypy` runs with `ignore_missing_imports = true`; stubs not required for CI as configured. |
| `pip-audit` / security scanner in CI | Process gap | Not a runtime missing package; no automated advisory gate. |
| Packaging metadata deps in `pyproject.toml` | Low | No installable package metadata; clone + `pip -r` workflow only. |

**No evidence** of missing libraries for charting/UI beyond Flet (no numpy/pandas/plotly imports in active `app/`).

---

## 3. Duplicate packages

| Item | Verdict |
|------|---------|
| Same package listed in multiple requirements files | **None** |
| Same package listed twice in one file | **None** |
| Overlapping explicit + transitive pins | **Yes (intentional overlap)** — see below |

**Overlaps (not file duplicates)**
- **`httpx`**: declared in `requirements.txt` and also required by `flet` (`httpx>=0.28.1`). Explicit pin matches Flet’s floor; useful for Telegram code and lock stability.
- **`msgpack`**: declared and also required by `flet`. Duplicate declaration of a transitive; see Unused.
- **`flet` ↔ `flet-desktop`**: mutual same-version pair (`0.85.3`). Not a duplicate package; required pairing. Drift would break desktop.

---

## 4. Version conflicts

| Check | Result |
|-------|--------|
| `pip check` (current `.venv`) | **No broken requirements** |
| Runtime pins vs each other | **No conflict** (exact pins resolve cleanly) |
| `flet` / `flet-desktop` versions | **Aligned** at `0.85.3` |
| Dev ranges vs runtime | **No hard conflict observed** |

**Soft / future risks (not current resolver failures)**
- `requirements-dev.txt` and `requirements-db.txt` use `>=` — two machines can install different majors (e.g. mypy 1.x vs 2.x). Local venv has `mypy 2.2.0`.
- Runtime pins are slightly behind latest PyPI as of audit date:
  - `ccxt` `4.5.64` → latest `4.5.68`
  - `flet` / `flet-desktop` `0.85.3` → latest `0.86.2`
  - Others checked are at latest (`httpx`, `SQLAlchemy`, `websocket-client`, `msgpack`, `python-dotenv`)
- Behind ≠ conflict; upgrade still needs regression testing (especially Flet minor bump).

---

## 5. Security risks

### Known CVEs (OSV.dev, queried this audit)

Pinned runtime packages and sampled high-impact transitives — **no OSV vulns reported**:

`flet`, `flet-desktop`, `httpx`, `msgpack`, `ccxt`, `python-dotenv`, `websocket-client`, `SQLAlchemy`, and transitives `requests`, `urllib3`, `aiohttp`, `cryptography` (versions present in local venv).

### Residual / structural risks (not CVE hits)

| Risk | Notes |
|------|-------|
| **Unpinned transitives** | Only top-level runtime packages are `==` pinned. Fresh installs can still float transitive minors within parent constraints. |
| **Unpinned dev/db specs** | `>=` ranges weaken reproducibility and can pull newly published vulnerable versions without a lockfile. |
| **Exchange / crypto supply chain** | `ccxt` + `cryptography` / `coincurve` / `aiohttp` are high-trust surface for a trading bot — keep pins current and review changelogs on bump. |
| **No CI `pip-audit`/OSV gate** | Advisories are not automatically blocking merges. |
| **Unsigned desktop launcher** | Outside PyPI, but release-relevant: macOS `.app` is unsigned (see `RELEASE_BUILD_AUDIT.md`). |

---

## 6. Deprecated libraries

| Library | Status |
|---------|--------|
| `websocket-client` | **Not deprecated** — actively maintained (1.9.0 current). |
| `SQLAlchemy` 2.x | **Current** major line (not 1.4 legacy). |
| `flet` 0.85.x | **Supported**; newer 0.86.x available (not a deprecation). |
| `ccxt` | **Active**; pinned build slightly behind latest patch. |
| `httpx` / `python-dotenv` / `msgpack` | **Current**. |
| `backup/ui_pyqt` (PyQt6) | Legacy backup tree; **not** a declared dependency — dead path relative to requirements. |

**None of the declared runtime packages are deprecated.**

---

## Scorecard

| Category | Finding |
|----------|---------|
| Unused packages | **`msgpack` only** (redundant pin) |
| Missing packages | **None required** for default SQLite/desktop path; optional DB drivers conditional |
| Duplicate packages | **No cross-file duplicates**; transitive overlaps for `httpx`/`msgpack` |
| Version conflicts | **None** (`pip check` clean) |
| Security risks | **No OSV hits today**; process/supply-chain residual risks remain |
| Deprecated libraries | **None** among declared deps |

---

## Recommendations (audit-only; not implemented)

1. Decide whether to keep **`msgpack`** as an explicit pin (document “pin transitive”) or drop it and rely on Flet.
2. Prefer `flet[desktop]==0.85.3` **or** keep explicit `flet` + `flet-desktop` pair — both valid; avoid version drift between them.
3. Add a lockfile or pin **dev/db** files if reproducible CI/operator installs matter.
4. Add periodic **`pip-audit` / OSV** to CI.
5. Treat **`ccxt` / Flet** bumps as controlled upgrades with regression tests — not silent float.

---

## Final judgment

Dependency set is **lean and production-reasonable** for this bot. No blocking missing packages, no resolver conflicts, no deprecated declared libraries, and no known OSV vulnerabilities on the pinned set at audit time. The only clear “unused declared package” is **`msgpack`**; the main quality gaps are **unpinned optional/dev specs** and **lack of automated advisory scanning**, not a broken dependency graph.
