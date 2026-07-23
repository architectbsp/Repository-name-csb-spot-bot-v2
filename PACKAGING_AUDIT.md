# PACKAGING AUDIT

**Question:** Can this application be distributed as a **standalone macOS application**?  
**Mode:** Read-only (no code modified)  
**Date:** 2026-07-23  
**Definition used:** A standalone macOS app is a signed (ideally notarized) `.app` / `.dmg` that end users can install and run **without** cloning the repo, installing Python, creating a venv, or running `pip` themselves.

---

## Executive verdict

**NO — not distributable as a standalone macOS application today.**

What exists is a **source-tree launcher**: a thin unsigned `.app` that bootstraps an adjacent git checkout (venv + `requirements.txt` + `main.py`). That is suitable for developers/operators who already have the repository. It is **not** a self-contained product binary.

| Distribution model | Supported now? |
|--------------------|----------------|
| Clone repo → double-click `launcher/CSB Spot Bot.app` | **Conditional yes** (see `RELEASE_BUILD_AUDIT.md`) |
| Ship only `CSB Spot Bot.app` to Desktop / Applications | **No** |
| Offline / notarized / App Store–style standalone | **No** |

---

## Checklist results

### 1. Launcher

| Item | Status | Detail |
|------|--------|--------|
| `.app` bundle present | Yes | `launcher/CSB Spot Bot.app` |
| Native Mach-O entry | **No** | `Contents/MacOS/CSB Spot Bot` is a **bash script** |
| Embeds app + Python runtime | **No** | Delegates to system `python3` + repo `.venv` |
| Relies on repo layout | **Yes** | Resolves `PROJECT_ROOT` as `../../../../` from `MacOS` |
| Can live alone in `/Applications` | **No** | Moving `.app` alone → missing `main.py` |
| Code signing | **None** | `codesign`: not signed at all |
| Notarization / stapling | **None** | |
| Gatekeeper-friendly | **No** | Clean Macs will warn/block |
| Side effects | Yes | Writes LaunchAgent + helper under `~/Library` |
| Icon / Resources | Empty | `Contents/Resources/` has no assets |

**Packaging implication:** The launcher is a **bootstrapper**, not a distributable product container.

---

### 2. venv

| Item | Status | Detail |
|------|--------|--------|
| Bundled inside `.app` | **No** | |
| Committed to git | **No** | `.venv/` gitignored (~256MB locally) |
| Created on first launch | Yes | In the **repository directory**, not inside the bundle |
| Requires host Python | **Yes** | `python3 -m venv` |
| Portable across machines | **No** | venv is machine/path-specific |

**Packaging implication:** Standalone distribution would need an embedded interpreter (e.g. PyInstaller, Briefcase, `flet pack`, conda-pack) — **not present**.

---

### 3. Requirements

| Item | Status | Detail |
|------|--------|--------|
| `requirements.txt` pinned | Yes | Exact `==` pins; small runtime set |
| Installed into the `.app` | **No** | `pip install -r` at first run into repo `.venv` |
| Needs network on first run | **Yes** | PyPI (+ Flet client cache under `~/.flet`) |
| Offline install | **No** | |
| Optional DB drivers | Separate | `requirements-db.txt` not part of default bootstrap |

**Packaging implication:** Dependency resolution is a **post-install build step**, incompatible with “copy `.app` and run offline.”

---

### 4. Assets

| Item | Status | Detail |
|------|--------|--------|
| Project `assets/` directory | **Missing** | Not in tree / not tracked |
| Flet assets path | Soft | Runtime may configure `…/assets`; non-fatal if unused |
| Bundled into `.app/Contents/Resources` | **No** | Resources folder empty |

**Packaging implication:** No packaged static asset pipeline for a standalone bundle.

---

### 5. Icons

| Item | Status | Detail |
|------|--------|--------|
| `.icns` / AppIcon | **Missing** | No logo/icon files in repo |
| `CFBundleIconFile` / asset catalog | **Missing** | Not in `Info.plist` |
| Dock / Finder branding | Generic | Default macOS placeholder icon |

**Packaging implication:** Not release-ready branding for a shipped Mac app.

---

### 6. Runtime files

| File / artifact | In `.app`? | How obtained | Standalone gap |
|-----------------|------------|--------------|----------------|
| `main.py` + `app/` | No | Must sit in cloned repo next to `launcher/` | **Blocking** |
| `.venv` | No | Created beside repo | **Blocking** |
| Flet desktop client | No | `~/.flet/client` (~135MB locally) | First-run download / external cache |
| SQLite DB | No | Created at runtime (`csb_spot_bot.db`) | OK if paths writable |
| Client-order / quarantine sidecars | No | Created at runtime | OK |
| Logs | No | `~/Library/Logs/CSBSpotBot/` | OK |
| LaunchAgent helper | No | Regenerated under Application Support | Operator residue; not a sealed app |

**Packaging implication:** Critical program code and interpreter live **outside** the bundle. Shipping the `.app` alone cannot run the product.

---

### 7. Configuration

| Item | Status | Detail |
|------|--------|--------|
| Secrets in bundle | Correctly absent | `.env` gitignored |
| Template shipped | Yes | `.env.example`, `config.example.json` in **repo**, not in `.app` |
| First-run config UI / wizard | **No** | User must copy/edit `.env` manually |
| Defaults without `.env` | Risky | Trading mode can resolve to **REAL** if unset; testnet defaults true |
| Config path model | CWD / env based | Assumes process cwd is project root (launcher `cd`s there) |

**Packaging implication:** Even a future frozen binary would still need a **documented secure config story** (Application Support `.env`, Keychain, first-run screen). That story is not packaged today.

---

## What would “standalone” require (gap summary)

Not prescriptions to implement now — only the audit gap list:

1. **Frozen runtime** inside the `.app` (Python + deps + `app/` + Flet client), or equivalent packager output  
2. **No dependency** on adjacent git checkout or host `python3`/`pip`  
3. **Writable data directory** outside the bundle for DB, sidecars, logs, `.env`  
4. **Code signing + notarization** for Gatekeeper  
5. **App icon** and non-empty Resources  
6. **First-run configuration** path that does not assume a developer clone  
7. **Single relocatable bundle** (Desktop / Applications) without LaunchAgent bootstrap hacks  

None of the above are complete in the current tree.

---

## Scorecard

| Area | Standalone-ready? |
|------|-------------------|
| Launcher | **No** (bootstrap only) |
| venv | **No** (external, host-built) |
| requirements | **No** (pip at runtime) |
| assets | **No** (missing / not bundled) |
| icons | **No** |
| runtime files | **No** (code outside bundle) |
| configuration | **Partial templates only** (not in-app) |

---

## Final judgment

**The application cannot be distributed as a standalone macOS application in its current form.**

It **can** be distributed as a **source repository** with a convenience `.app` launcher for operators who clone the project, install Python 3.12+, allow an unsigned app, and configure `.env`. That is a different product shape than a sealed Mac app.

Related audits: `RELEASE_BUILD_AUDIT.md` (clean clone), `DEPENDENCY_AUDIT.md` (PyPI surface), prior launcher production notes.
