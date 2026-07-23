# RELEASE BUILD AUDIT

**Scope:** Clean macOS clone → double-click `launcher/CSB Spot Bot.app` still works  
**Mode:** Read-only verification (no code modified)  
**Date:** 2026-07-23  
**Repo state audited:** `cursor/optimizer-multi-strategy` (launcher commit included)

---

## Executive verdict

**CONDITIONAL PASS — not a turnkey clean-machine release.**

After `git clone`, the committed `.app` **can** resolve the project via relative paths, create `.venv`, install pinned `requirements.txt`, and start `main.py` **if** the machine already has a suitable `python3`, network access, and the user allows an **unsigned** app. It is **not** a self-contained offline installer and has several missing operator/runtime assets that a clean Mac will not have.

| Question | Answer |
|----------|--------|
| Can the repo be cloned and the launcher still find the project? | **Yes** (if `.app` stays under `launcher/`) |
| Will double-click work with zero extra setup? | **No** |
| Is this production-quality release packaging? | **No** |

---

## 1. Python environment

| Check | Result |
|-------|--------|
| Declared requirement | `pyproject.toml` → `requires-python = ">=3.12"` |
| CI | `.github/workflows/ci.yml` pins Python **3.12** |
| Launcher version gate | **Missing** — only checks `command -v python3` |
| Clean Mac with system/Homebrew Python 3.11 | **Likely fail** after venv create (no preflight) |
| Clean Mac with no Python | Alert: “python3 was not found” |
| Clean Mac with Python 3.12+ on PATH | **Supported path** |

**Problems**
- No explicit `python3.12` preference; first `python3` on PATH wins.
- No Xcode CLT / Homebrew install guidance in-repo (**no README**).
- Apple Silicon vs Intel: PATH includes `/opt/homebrew/bin` and `/usr/local/bin` (good), but still depends on user install.

---

## 2. Launcher

| Check | Result |
|-------|--------|
| Bundle committed | Yes: `Info.plist`, `MacOS/CSB Spot Bot`, `PkgInfo` |
| Executable bit in git archive | **Preserved** (`-rwxr-xr-x`) |
| Rebuild scripts committed | `launcher/build_macos_app.sh`, `launcher/macos_app_executable.sh` |
| Unsigned | **Yes** — Gatekeeper risk on fresh download/clone |
| Empty `Contents/Resources/` | Not in git (empty dirs omitted) — **harmless** |
| Mechanism | Writes helper + LaunchAgent, then `kickstart` (needed for Desktop TCC) |

**Clean-clone launch sequence (expected)**
1. Double-click `launcher/CSB Spot Bot.app`
2. May hit Gatekeeper (“unidentified developer”) → user must allow
3. Entry script resolves repo root, writes `~/Library/Application Support/CSBSpotBot/start_bot.sh`
4. Registers `~/Library/LaunchAgents/com.csb.spotbot.gui.plist`
5. Agent creates `.venv` if missing, `pip install -r requirements.txt`, runs `main.py`
6. Logs: `~/Library/Logs/CSBSpotBot/launcher.log`

**Problems**
- Unsigned / not notarized → friction or block on clean Macs.
- First launch can take minutes (pip + Flet client) with little UI feedback.
- Relaunch uses `kickstart -k` (hard-restarts a running bot).
- No README documenting Desktop **alias/symlink** rule (moving `.app` alone breaks paths).

---

## 3. Virtual environment

| Check | Result |
|-------|--------|
| `.venv` in git? | **No** (gitignored) — correct |
| Auto-create on first launch? | **Yes** (`python3 -m venv .venv`) |
| `pip upgrade` then install? | **Yes** |
| Recreate if broken? | **Partial** — missing `bin/python` fails (log only, weak alert path) |
| Location | `<repo>/.venv` (relative to project root) |

**Problems**
- First-run venv build requires **network** and writable repo directory.
- If clone is on Desktop, LaunchAgent path is required (already implemented); direct-in-app Python without agent fails TCC (known).
- No hash/lock beyond pin lines in `requirements.txt` (pins exist; no `requirements.lock` / uv lock).

---

## 4. Dependencies

| File | Tracked | Used by launcher? |
|------|---------|-------------------|
| `requirements.txt` | Yes | **Yes** (runtime) |
| `requirements-dev.txt` | Yes | No (CI/tests only) |
| `requirements-db.txt` | Yes | No (optional Postgres/MySQL) |

**Pinned runtime (`requirements.txt`)**
- `flet==0.85.3`, `flet-desktop==0.85.3`, `httpx`, `msgpack`, `ccxt`, `python-dotenv`, `websocket-client`, `SQLAlchemy`
- Pinning regression test exists: `tests/test_requirements_pinning.py`

**Problems**
- Clean machine needs **PyPI access** on first run.
- `flet-desktop` may download/cache client under `~/.flet/client/` (extra network; not in repo).
- Optional DB drivers not installed by launcher (OK for default SQLite; breaks if `.env`/`config` points at Postgres/MySQL without manual `requirements-db.txt`).
- Dev tools not needed for launch (OK).

---

## 5. Relative paths

| Check | Result |
|-------|--------|
| Resolution rule | `Contents/MacOS` → `../../../../` = repo root |
| Simulated `git archive` extract | **Resolves `main.py` + `requirements.txt` correctly** |
| Constraint | `.app` must remain at `<repo>/launcher/CSB Spot Bot.app` |
| Desktop copy of `.app` alone | **Breaks** |
| Desktop symlink/alias to bundle | **OK** (supported pattern) |

**Problems**
- Easy operator mistake: drag `.app` to Desktop instead of alias.
- Absolute paths are baked into runtime helper/LaunchAgent **per machine** on each launch (rewritten) — fine after first double-click on that clone path; moving the repo later requires launching again from the new location (or stale agent points at old path until next successful `.app` start).

---

## 6. Missing assets

| Asset | In repo? | Impact on clean launch |
|-------|----------|------------------------|
| App icon (`.icns`) | **No** | Generic icon only |
| `assets/` (Flet) | **No** (and not present locally) | Flet still configures an assets path; typically non-fatal if unused |
| README / macOS setup guide | **No** | Clean-machine operators lack steps |
| Branding / logo | **No** | Cosmetic only |

**Problems**
- Missing README is the largest release gap for “clone on clean Mac.”
- No icon is a packaging quality gap, not a functional blocker.

---

## 7. Missing runtime files

| File | Tracked? | Required for first UI start? | Notes |
|------|----------|------------------------------|-------|
| `.env` | No (gitignored); `.env.example` yes | **Not strictly** for process start | Exchange keys needed for real trading; UI warns about keys |
| `config.json` | No; `config.example.json` yes | **No** | Defaults to SQLite `csb_spot_bot.db` |
| `csb_spot_bot.db` | No (gitignored) | **No** | Created at runtime |
| Client-order / quarantine sidecars | No (gitignored) | **No** | Created when execution path needs them |
| `.venv` | No | Created by launcher | |
| Flet desktop client cache | Outside repo (`~/.flet`) | Downloaded/cached on demand | Offline clean Mac fails if not cached |
| Telegram / API secrets | Not in repo | Optional | Correct |

**Ops footgun on clean machine**
- If `.env` is missing/incomplete, trading mode resolution defaults toward **REAL** when `TRADE_MODE`/`PAPER_TRADING` unset (`resolve_trading_mode()`), while testnet defaults **true** in settings — confusing first-run posture; not launcher-specific but release-relevant.

---

## Clean macOS machine — expected success path

1. Install **Python 3.12+** (`python3` on PATH).
2. `git clone <repo>` (keep folder structure; do not relocate only the `.app`).
3. Optional but recommended: `cp .env.example .env` and fill keys; set paper/testnet intentionally.
4. First double-click: allow Gatekeeper if prompted.
5. Wait for venv + pip + Flet client (watch `~/Library/Logs/CSBSpotBot/launcher.log` if nothing appears).
6. Optional Desktop shortcut:  
   `ln -sf "$(pwd)/launcher/CSB Spot Bot.app" ~/Desktop/"CSB Spot Bot.app"`
7. If bundle corrupted: `./launcher/build_macos_app.sh`

---

## Clean macOS machine — failure modes

| Failure | Cause |
|---------|--------|
| Gatekeeper block | Unsigned app / quarantine |
| Alert: python3 not found | No Python on PATH |
| Import/syntax errors after venv | Python &lt; 3.12 |
| Long hang / pip errors | No network / PyPI blocked |
| Alert: main.py not found | `.app` moved out of `launcher/` |
| UI up but no trading | Missing `.env` credentials |
| DB driver errors | Non-SQLite config without `requirements-db.txt` |
| Abrupt kill on 2nd double-click | `kickstart -k` relaunch behavior |

---

## Scorecard

| Area | Clean-clone readiness |
|------|----------------------|
| Python environment | **Partial** (3.12 required, not enforced) |
| Launcher | **Partial** (works if Gatekeeper + layout OK) |
| Virtual environment | **Pass** (auto-create) |
| Dependencies | **Pass** with network (pins present) |
| Relative paths | **Pass** with layout constraint |
| Missing assets | **Fail** for release polish (README/icon) |
| Missing runtime files | **Pass** for defaults; **Partial** for secrets/config |

---

## Final judgment

**The repository can be cloned on a clean macOS machine and the launcher can still work**, but only as a **source + bootstrap launcher**, not as a sealed release artifact.

It will **not** reliably “just work” for a non-technical user with zero prerequisites. Treat current packaging as **developer/operator grade**, not App Store / notarized production distribution.
