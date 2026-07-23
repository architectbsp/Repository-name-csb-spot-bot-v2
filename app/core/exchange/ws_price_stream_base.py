from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import websocket

from app.core.exchange.stream import PriceStream
from app.core.market_data.models import NormalizedTicker


logger = logging.getLogger(__name__)


class WebsocketPriceStreamBase(PriceStream, ABC):
    """
    Shared WebSocket lifecycle (connect / reconnect / subscribe /
    unsubscribe / keepalive) for exchange-specific ticker price streams.

    Architectural rule (see docs/ARCHITECTURE.md, "Exchange Agnostic
    Design"): every exchange owns a fully independent PriceStream
    instance -- its own thread, its own socket, its own symbol
    subscriptions and its own `NormalizedTicker.exchange` tag. Nothing in
    this base class (or its subclasses) ever reads state from another
    exchange's stream, so data can never cross between exchanges.

    Subclasses only need to implement the exchange-specific wire format:
    the endpoint URL, symbol formatting, subscribe/unsubscribe payloads,
    optional keepalive payload and raw-message-to-NormalizedTicker
    parsing. Everything else (threading, reconnect-with-backoff, JSON
    decoding, defensive error handling) is identical across exchanges and
    lives here once.
    """

    RECONNECT_DELAY_SECONDS = 5
    PING_INTERVAL_SECONDS = 15
    PING_TIMEOUT_SECONDS = 5
    KEEPALIVE_INTERVAL_SECONDS: float | None = None

    def __init__(self) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._lock = threading.RLock()
        self._callback: Callable[[str, Any], None] | None = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._ws: websocket.WebSocketApp | None = None
        self._connected = threading.Event()

        self._keepalive_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Exchange-specific hooks (must be implemented by subclasses)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def _url(self) -> str:
        """WebSocket endpoint URL for this exchange/network."""

    @abstractmethod
    def _to_wire_symbol(self, symbol: str) -> str:
        """Converts an internal 'BTC/USDT'-style symbol into whatever
        format this exchange expects on the wire."""

    @abstractmethod
    def _subscribe_payload(self, wire_symbols: list[str]) -> Any | None:
        """Returns the JSON-serializable payload used to subscribe to
        ticker updates for `wire_symbols`, or None to send nothing."""

    @abstractmethod
    def _unsubscribe_payload(self, wire_symbols: list[str]) -> Any | None:
        """Returns the JSON-serializable payload used to unsubscribe from
        ticker updates for `wire_symbols`, or None to send nothing."""

    @abstractmethod
    def _parse_ticker(self, data: dict) -> NormalizedTicker | None:
        """Returns a NormalizedTicker if `data` is a ticker update,
        otherwise None (ack/heartbeat/unrelated message)."""

    def _keepalive_payload(self) -> Any | None:
        """Optional application-level keepalive payload, sent every
        KEEPALIVE_INTERVAL_SECONDS while connected. Return a dict to send
        as JSON, a str to send raw, or None (default) to disable."""
        return None

    # ------------------------------------------------------------------
    # Shared symbol-formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _usdt_pair_from_compact(compact_symbol: str) -> str:
        """Converts a compact 'BTCUSDT'-style wire symbol into the
        internal 'BTC/USDT' convention used across the codebase."""
        compact_symbol = compact_symbol.upper()

        if compact_symbol.endswith("USDT"):
            return f"{compact_symbol[:-4]}/USDT"

        return compact_symbol

    @staticmethod
    def _pair_from_dashed(dashed_symbol: str) -> str:
        """Converts a dashed 'BTC-USDT'-style wire symbol into the
        internal 'BTC/USDT' convention used across the codebase."""
        return dashed_symbol.upper().replace("-", "/")

    # ------------------------------------------------------------------
    # Generic lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        symbols: list[str],
        callback: Callable[[str, Any], None],
    ) -> None:
        if self._running:
            return

        with self._lock:
            self._symbols = sorted(set(symbols))

        self._callback = callback
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            name=type(self).__name__,
        )

        self._running = True
        self._thread.start()

        if self.KEEPALIVE_INTERVAL_SECONDS:
            self._keepalive_thread = threading.Thread(
                target=self._run_keepalive,
                name=f"{type(self).__name__}-keepalive",
                daemon=True,
            )
            self._keepalive_thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._connected.clear()
        self._running = False
        self._stop_event.set()

        ws = self._ws
        self._ws = None

        if ws is not None:
            try:
                ws.close()
            except Exception:
                logger.debug(
                    "[%s] websocket close during stop raised",
                    type(self).__name__,
                    exc_info=True,
                )

        if self._thread is not None:
            self._thread.join(timeout=5)

        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=2)

        self._thread = None
        self._keepalive_thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._ws = websocket.WebSocketApp(
                self._url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )

            self._ws.run_forever(
                ping_interval=self.PING_INTERVAL_SECONDS,
                ping_timeout=self.PING_TIMEOUT_SECONDS,
            )

            if self._stop_event.is_set():
                break

            time.sleep(self.RECONNECT_DELAY_SECONDS)

    def _run_keepalive(self) -> None:
        interval = self.KEEPALIVE_INTERVAL_SECONDS or 0

        while not self._stop_event.wait(interval):
            if not self._connected.is_set() or self._ws is None:
                continue

            payload = self._keepalive_payload()

            if payload is None:
                continue

            try:
                message = (
                    payload if isinstance(payload, str) else json.dumps(payload)
                )
                self._ws.send(message)
            except Exception:
                logger.debug(
                    "[%s] Keepalive send failed (likely reconnecting)",
                    type(self).__name__,
                )

    def _send(self, payload: Any | None) -> None:
        if payload is None or self._ws is None:
            return

        message = payload if isinstance(payload, str) else json.dumps(payload)

        try:
            self._ws.send(message)
        except Exception:
            logger.exception(
                "[%s] Failed to send websocket message",
                type(self).__name__,
            )

    def _on_open(self, ws) -> None:
        self._connected.set()
        logger.info("[%s] websocket connected", type(self).__name__)

        if self._callback:
            self._callback(
                "exchange.connected",
                {
                    "stream": type(self).__name__,
                    "exchange": getattr(self, "exchange_name", type(self).__name__),
                },
            )

        with self._lock:
            symbols = list(self._symbols)

        if not symbols:
            return

        self._send(
            self._subscribe_payload(
                [self._to_wire_symbol(symbol) for symbol in symbols]
            )
        )

    def _on_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
        except Exception:
            logger.debug(
                "[%s] Non-JSON websocket message ignored: %.200s",
                type(self).__name__,
                message,
            )
            return

        try:
            ticker = self._parse_ticker(data)
        except Exception:
            logger.exception(
                "[%s] Failed to parse websocket message: %.200s",
                type(self).__name__,
                message,
            )
            return

        if ticker is None:
            return

        if self._callback:
            self._callback("ticker.updated", ticker)

    def _on_error(self, ws, error) -> None:
        self._connected.clear()
        logger.exception(
            "[%s] websocket error: %s",
            type(self).__name__,
            error,
        )
        if self._callback:
            self._callback(
                "exchange.disconnected",
                {
                    "stream": type(self).__name__,
                    "exchange": getattr(
                        self, "exchange_name", type(self).__name__
                    ),
                    "error": str(error),
                },
            )

    def _on_close(self, ws, code, msg) -> None:
        self._connected.clear()
        logger.warning(
            "[%s] websocket closed (%s): %s",
            type(self).__name__,
            code,
            msg,
        )
        if self._callback:
            self._callback(
                "exchange.disconnected",
                {
                    "stream": type(self).__name__,
                    "exchange": getattr(
                        self, "exchange_name", type(self).__name__
                    ),
                    "detail": f"closed ({code}): {msg}",
                },
            )

    def update_symbols(self, symbols: list[str]) -> None:
        symbols = sorted(set(symbols))

        with self._lock:
            current = set(self._symbols)
            target = set(symbols)

            added = sorted(target - current)
            removed = sorted(current - target)

            self._symbols = symbols

        if not self._running or self._ws is None or not self._connected.is_set():
            return

        if added:
            self._send(
                self._subscribe_payload(
                    [self._to_wire_symbol(symbol) for symbol in added]
                )
            )

        if removed:
            self._send(
                self._unsubscribe_payload(
                    [self._to_wire_symbol(symbol) for symbol in removed]
                )
            )

    @property
    def running(self) -> bool:
        return self._running
