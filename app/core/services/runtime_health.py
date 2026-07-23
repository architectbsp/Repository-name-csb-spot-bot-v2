"""
R7 -- production runtime observability (read-only aggregation).

Assembles existing Worker / Scheduler / Exchange / Telemetry / OES /
persistence signals into one operator-facing snapshot. Never places
orders or mutates trading state.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from app.core.exchange.models import ConnectionStatus
from app.core.security.redact import redact_secrets


logger = logging.getLogger(__name__)

# Operator thresholds (seconds).
_WORKER_STALL_SECONDS = 30.0
_WS_STALE_SECONDS = 60.0
_DB_CHECK_MIN_INTERVAL_SECONDS = 60.0


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _overdue_seconds(next_run: datetime | None, *, now: datetime) -> float | None:
    if next_run is None:
        return None
    try:
        return max(0.0, (now - next_run).total_seconds())
    except Exception:
        return None


class RuntimeHealthService:
    """
    Builds a redacted health snapshot from BotEngine dependencies.
    Safe to call frequently from diagnostics / operator tools.
    """

    def __init__(self) -> None:
        self._engine = None
        self._last_db_check_at: float | None = None
        self._last_db_status: str | None = None
        self._last_db_ok: bool | None = None

    def set_engine(self, engine) -> None:
        self._engine = engine

    def snapshot(self) -> dict[str, Any]:
        engine = self._engine
        if engine is None:
            return {
                "alive": False,
                "degraded": True,
                "mode": "unwired",
                "issues": ["engine_unwired"],
            }

        now = datetime.now()
        issues: list[str] = []

        worker = self._worker_section(engine, now, issues)
        scheduler = self._scheduler_section(engine, now, issues)
        exchanges = self._exchange_section(engine, issues)
        websocket = self._websocket_section(engine, issues)
        orders = self._orders_section(engine)
        recovery = self._recovery_section(engine, issues)
        persistence = self._persistence_section(engine, issues)
        event_bus = self._event_bus_section(engine)
        telemetry = self._telemetry_section(engine)

        degraded = bool(issues)
        mode = "degraded" if degraded else ("running" if engine.running else "stopped")

        snapshot = {
            "alive": bool(getattr(engine, "running", False)),
            "degraded": degraded,
            "mode": mode,
            "issues": issues,
            "worker": worker,
            "scheduler": scheduler,
            "exchanges": exchanges,
            "websocket": websocket,
            "orders": orders,
            "recovery": recovery,
            "persistence": persistence,
            "event_bus": event_bus,
            "telemetry": telemetry,
            "checked_at": now.isoformat(),
        }
        # Keep BotEngine.runtime_health in sync for existing readers.
        runtime = getattr(engine, "runtime_health", None)
        if isinstance(runtime, dict):
            runtime["degraded"] = degraded
            runtime["mode"] = mode
            runtime["issues"] = list(issues)
            runtime["last_health_at"] = snapshot["checked_at"]
            runtime["exchange_connected"] = bool(exchanges.get("any_connected"))
            runtime["websocket_ok"] = bool(websocket.get("ok"))
            runtime["scheduler_ok"] = bool(scheduler.get("ok"))
            runtime["persistence_ok"] = bool(persistence.get("ok"))
            runtime["recovery_attention"] = bool(recovery.get("attention"))
        return snapshot

    def _worker_section(self, engine, now: datetime, issues: list[str]) -> dict:
        worker = getattr(engine, "worker", None)
        if worker is None or not hasattr(worker, "health"):
            issues.append("worker_missing")
            return {"ok": False, "present": False}

        health = worker.health()
        last_tick = getattr(health, "last_tick_at", None)
        stall_seconds = None
        if last_tick is not None and engine.running:
            try:
                stall_seconds = max(0.0, (now - last_tick).total_seconds())
            except Exception:
                stall_seconds = None

        ok = True
        if engine.running and not health.thread_alive:
            ok = False
            issues.append("worker_thread_dead")
        if engine.running and not health.active:
            ok = False
            issues.append("worker_inactive")
        if stall_seconds is not None and stall_seconds > _WORKER_STALL_SECONDS:
            ok = False
            issues.append("worker_stalled")
        if health.consecutive_errors >= 3:
            ok = False
            issues.append("worker_error_burst")

        return {
            "ok": ok,
            "present": True,
            "active": health.active,
            "thread_alive": health.thread_alive,
            "error_count": health.error_count,
            "consecutive_errors": health.consecutive_errors,
            "last_error": redact_secrets(health.last_error),
            "last_error_at": _iso(health.last_error_at),
            "last_tick_at": _iso(last_tick),
            "stall_seconds": stall_seconds,
        }

    def _scheduler_section(self, engine, now: datetime, issues: list[str]) -> dict:
        scheduler = getattr(engine, "scheduler", None)
        if scheduler is None:
            issues.append("scheduler_missing")
            return {"ok": False, "present": False, "jobs": []}

        running = bool(getattr(scheduler, "running", False))
        jobs_out: list[dict] = []
        delayed = 0
        for name, job in (getattr(scheduler, "jobs", {}) or {}).items():
            interval = float(getattr(job, "interval", 0) or 0)
            overdue = _overdue_seconds(getattr(job, "next_run", None), now=now)
            job_delayed = (
                engine.running
                and running
                and bool(getattr(job, "enabled", True))
                and overdue is not None
                and interval > 0
                and overdue > (interval * 2.0)
            )
            if job_delayed:
                delayed += 1
            jobs_out.append(
                {
                    "name": name,
                    "enabled": bool(getattr(job, "enabled", True)),
                    "running": bool(getattr(job, "running", False)),
                    "interval": interval,
                    "last_run": _iso(getattr(job, "last_run", None)),
                    "next_run": _iso(getattr(job, "next_run", None)),
                    "overdue_seconds": overdue,
                    "delayed": job_delayed,
                    "last_error": redact_secrets(getattr(job, "last_error", None)),
                }
            )

        ok = True
        if engine.running and not running:
            ok = False
            issues.append("scheduler_stopped")
        if delayed:
            ok = False
            issues.append("scheduler_jobs_delayed")

        return {
            "ok": ok,
            "present": True,
            "running": running,
            "job_count": len(jobs_out),
            "delayed_jobs": delayed,
            "jobs": jobs_out,
        }

    def _exchange_section(self, engine, issues: list[str]) -> dict:
        exchange_mgr = getattr(engine, "exchange", None)
        venues: list[dict] = []
        any_connected = False
        any_error = False
        if exchange_mgr is not None and hasattr(exchange_mgr, "enabled"):
            for ex in exchange_mgr.enabled() or []:
                state = getattr(ex, "state", None)
                status = getattr(state, "status", None)
                status_name = (
                    status.name if hasattr(status, "name") else str(status)
                )
                connected = status == ConnectionStatus.CONNECTED
                errored = status == ConnectionStatus.ERROR
                any_connected = any_connected or connected
                any_error = any_error or errored
                stream = None
                get_stream = getattr(ex, "get_price_stream", None)
                if callable(get_stream):
                    try:
                        stream = get_stream()
                    except Exception:
                        stream = None
                ws_running = bool(getattr(stream, "running", False)) if stream else False
                ws_connected = None
                if stream is not None and hasattr(stream, "connected"):
                    try:
                        ws_connected = bool(stream.connected)
                    except Exception:
                        ws_connected = None
                venues.append(
                    {
                        "exchange": getattr(
                            getattr(state, "exchange", None), "name", "?"
                        ),
                        "status": status_name,
                        "connected": connected,
                        "last_error": redact_secrets(
                            getattr(state, "last_error", None)
                        ),
                        "ws_running": ws_running,
                        "ws_connected": ws_connected,
                    }
                )

        ok = True
        if engine.running and venues and not any_connected:
            ok = False
            issues.append("exchange_disconnected")
        if any_error:
            ok = False
            issues.append("exchange_error")

        return {
            "ok": ok,
            "any_connected": any_connected,
            "venues": venues,
        }

    def _websocket_section(self, engine, issues: list[str]) -> dict:
        telemetry = self._telemetry_section(engine)
        data_age = telemetry.get("data_age_seconds")
        stale = (
            data_age is not None and float(data_age) > _WS_STALE_SECONDS
        )
        # If bot is running and we expect market data, missing age is also stale.
        missing = engine.running and data_age is None
        ok = not stale and not missing
        if stale:
            issues.append("websocket_stale")
        if missing:
            # Not always fatal (scan-only boot); mark attention without forcing
            # degraded unless exchanges claim WS running.
            exchanges = getattr(engine, "exchange", None)
            ws_expected = False
            if exchanges is not None and hasattr(exchanges, "enabled"):
                for ex in exchanges.enabled() or []:
                    stream = getattr(ex, "get_price_stream", lambda: None)()
                    if stream is not None and getattr(stream, "running", False):
                        ws_expected = True
                        break
            if ws_expected:
                ok = False
                issues.append("websocket_inactive")

        return {
            "ok": ok,
            "data_age_seconds": data_age,
            "stale_threshold_seconds": _WS_STALE_SECONDS,
        }

    def _orders_section(self, engine) -> dict:
        telemetry = self._telemetry_section(engine)
        oes = None
        try:
            oes = engine.risk_manager.order_execution
        except Exception:
            oes = None
        return {
            "order_latency_ms": telemetry.get("order_latency_ms"),
            "api_latency_ms": telemetry.get("api_latency_ms"),
            "flowing": telemetry.get("order_latency_ms") is not None,
            "quarantined_count": (
                len(oes.list_quarantined())
                if oes is not None and hasattr(oes, "list_quarantined")
                else 0
            ),
        }

    def _recovery_section(self, engine, issues: list[str]) -> dict:
        oes = None
        try:
            oes = engine.risk_manager.order_execution
        except Exception:
            oes = None
        quarantined: list[str] = []
        active: list[dict] = []
        if oes is not None:
            if hasattr(oes, "list_quarantined"):
                quarantined = list(oes.list_quarantined())
            if hasattr(oes, "list_active_client_orders"):
                active = list(oes.list_active_client_orders())
        attention = bool(quarantined) or bool(active)
        unresolved = any(
            str(item.get("status", "")).upper() in {"AMBIGUOUS", "AWAITING_LOCAL"}
            for item in active
        )
        if unresolved:
            issues.append("recovery_unresolved")
        return {
            "attention": attention,
            "quarantined": quarantined,
            "quarantined_count": len(quarantined),
            "active_client_orders": active,
            "active_client_order_count": len(active),
            "unresolved": unresolved,
        }

    def _persistence_section(self, engine, issues: list[str]) -> dict:
        persistence = getattr(engine, "persistence", None)
        if persistence is None:
            issues.append("persistence_missing")
            return {"ok": False, "present": False, "detail": None}

        now = time.monotonic()
        if (
            self._last_db_check_at is not None
            and (now - self._last_db_check_at) < _DB_CHECK_MIN_INTERVAL_SECONDS
            and self._last_db_ok is not None
        ):
            ok = bool(self._last_db_ok)
            if not ok:
                issues.append("persistence_unhealthy")
            return {
                "ok": ok,
                "present": True,
                "detail": self._last_db_status,
                "cached": True,
            }

        ok = True
        detail = "ok"
        try:
            from app.core.persistence.database import sqlite_quick_check_status

            engine_obj = getattr(persistence, "engine", None)
            if engine_obj is None:
                try:
                    from app.core.persistence.database import get_engine

                    engine_obj = get_engine()
                except Exception:
                    engine_obj = None
            if engine_obj is None:
                detail = "engine_unavailable"
                ok = False
            else:
                detail = sqlite_quick_check_status(engine_obj)
                ok = detail in {"ok", "n/a"}
        except Exception as exc:
            ok = False
            detail = redact_secrets(f"{type(exc).__name__}: {exc}")
            logger.exception("[HEALTH] persistence check failed")

        self._last_db_check_at = now
        self._last_db_ok = ok
        self._last_db_status = detail
        if not ok:
            issues.append("persistence_unhealthy")
        return {
            "ok": ok,
            "present": True,
            "detail": detail,
            "cached": False,
        }

    def _event_bus_section(self, engine) -> dict:
        bus = getattr(engine, "event_bus", None)
        if bus is None:
            return {"ok": False, "present": False}
        stats = {}
        if hasattr(bus, "stats"):
            try:
                stats = dict(bus.stats())
            except Exception:
                stats = {}
        handler_errors = int(stats.get("handler_errors", 0) or 0)
        return {
            "ok": handler_errors == 0 or handler_errors < 100,
            "present": True,
            "publish_count": stats.get("publish_count"),
            "handler_errors": handler_errors,
            "topic_count": stats.get("topic_count"),
        }

    def _telemetry_section(self, engine) -> dict:
        telemetry = getattr(engine, "telemetry", None)
        if telemetry is None or not hasattr(telemetry, "collect"):
            return {}
        try:
            snap = telemetry.collect()
        except Exception:
            logger.debug("[HEALTH] telemetry.collect failed", exc_info=True)
            return {}
        return {
            "order_latency_ms": getattr(snap, "order_latency_ms", None),
            "data_age_seconds": getattr(snap, "data_age_seconds", None),
            "api_latency_ms": getattr(snap, "api_latency_ms", None),
            "scan_elapsed_ms": getattr(snap, "loop_time_ms", None),
            "pipeline_ms": getattr(snap, "pipeline_ms", None),
            "ram_mb": getattr(snap, "ram_mb", None),
            "cpu_percent": getattr(snap, "cpu_percent", None),
        }
