"""
Sprint 12 -- Execution & Data Telemetry.

Tracks order latency, data freshness, scanner/pipeline loop time, API
ping, and process RAM/CPU for the live dashboard. Never places orders
or mutates trading state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from app.core.services.system_metrics import SystemMetricsSampler


logger = logging.getLogger(__name__)

_API_PING_MIN_INTERVAL_SECONDS = 15.0
_ORDER_LATENCY_WINDOW = 20


@dataclass(slots=True)
class TelemetrySnapshot:
    order_latency_ms: float | None = None
    data_age_seconds: float | None = None
    loop_time_ms: float | None = None
    pipeline_ms: float | None = None
    api_latency_ms: float | None = None
    ram_mb: float | None = None
    cpu_percent: float | None = None


class TelemetryService:
    """
    Periodic / event-driven metrics collector. DashboardService calls
    ``collect()`` on each UI poll; OrderExecutionService records order
    round-trips via ``record_order_latency``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._system = SystemMetricsSampler()
        self._order_latencies_ms: deque[float] = deque(
            maxlen=_ORDER_LATENCY_WINDOW
        )
        self._loop_time_ms: float | None = None
        self._pipeline_ms: float | None = None
        self._last_api_latency_ms: float | None = None
        self._last_api_ping_at: float | None = None
        self._exchange_manager = None
        self._market_scanner = None

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_market_scanner(self, market_scanner) -> None:
        self._market_scanner = market_scanner

    def record_order_latency(self, elapsed_ms: float) -> None:
        if elapsed_ms < 0:
            return
        with self._lock:
            self._order_latencies_ms.append(float(elapsed_ms))

    def record_pipeline_ms(self, elapsed_ms: float) -> None:
        with self._lock:
            self._pipeline_ms = float(elapsed_ms)

    def on_scan_completed(self, event) -> None:
        """EventBus ``market_scanner.scan_completed`` -- loop time."""
        if not isinstance(event, dict):
            return
        elapsed = event.get("elapsed_ms")
        if elapsed is None:
            return
        try:
            with self._lock:
                self._loop_time_ms = float(elapsed)
        except (TypeError, ValueError):
            return

    def collect(
        self,
        *,
        tickers: dict | None = None,
        now_seconds: float | None = None,
    ) -> TelemetrySnapshot:
        """
        Build a point-in-time telemetry snapshot for the UI.

        ``tickers`` is an optional mapping of cache-key → NormalizedTicker
        (or any object with a ``timestamp`` attribute in epoch ms).
        """
        system = self._system.sample()
        api_ms = self._sample_api_latency()
        loop_ms = self._resolve_loop_time_ms()
        with self._lock:
            order_ms = (
                sum(self._order_latencies_ms) / len(self._order_latencies_ms)
                if self._order_latencies_ms
                else None
            )
            pipeline_ms = self._pipeline_ms

        data_age = self._data_age_seconds(tickers, now_seconds=now_seconds)

        return TelemetrySnapshot(
            order_latency_ms=order_ms,
            data_age_seconds=data_age,
            loop_time_ms=loop_ms,
            pipeline_ms=pipeline_ms,
            api_latency_ms=api_ms,
            ram_mb=system.ram_mb,
            cpu_percent=system.cpu_percent,
        )

    def _resolve_loop_time_ms(self) -> float | None:
        with self._lock:
            cached = self._loop_time_ms
        if cached is not None:
            return cached
        if self._market_scanner is None:
            return None
        getter = getattr(self._market_scanner, "last_scan_elapsed_ms", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def _sample_api_latency(self) -> float | None:
        if self._exchange_manager is None:
            return self._last_api_latency_ms

        now = time.perf_counter()
        if (
            self._last_api_ping_at is not None
            and (now - self._last_api_ping_at) < _API_PING_MIN_INTERVAL_SECONDS
        ):
            return self._last_api_latency_ms

        try:
            self._last_api_latency_ms = float(self._exchange_manager.ping_ms())
            self._last_api_ping_at = now
        except Exception:
            logger.debug("[TELEMETRY] API ping failed", exc_info=True)
            self._last_api_ping_at = now

        return self._last_api_latency_ms

    @staticmethod
    def _data_age_seconds(
        tickers: dict | None,
        *,
        now_seconds: float | None = None,
    ) -> float | None:
        if not tickers:
            return None
        now_ms = int((now_seconds if now_seconds is not None else time.time()) * 1000)
        ages: list[float] = []
        for ticker in tickers.values():
            ts = getattr(ticker, "timestamp", None)
            if ts is None:
                continue
            try:
                ts_i = int(ts)
            except (TypeError, ValueError):
                continue
            if ts_i <= 0:
                continue
            # Heuristic: values < 1e12 are seconds; exchange feeds use ms.
            if ts_i < 1_000_000_000_000:
                ts_i *= 1000
            age = max(0.0, (now_ms - ts_i) / 1000.0)
            ages.append(age)
        if not ages:
            return None
        return max(ages)
