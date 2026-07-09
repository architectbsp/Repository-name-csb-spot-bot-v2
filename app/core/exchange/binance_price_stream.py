from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import websocket
import logging

from app.core.exchange.stream import PriceStream


logger = logging.getLogger(__name__)


class BinancePriceStream(PriceStream):
    BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._lock = threading.RLock()
        self._callback: Callable[[dict[str, Any]], None] | None = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._ws: websocket.WebSocketApp | None = None
        self._connected = threading.Event()

    def start(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        if self._running:
            return

        with self._lock:
            self._symbols = sorted(set(symbols))
        self._callback = callback

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="BinancePriceStream",
        )

        self._running = True
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._connected.clear()

        self._running = False

        self._connected.clear()

        self._stop_event.set()

        if self._ws is not None:
            self._ws.close()

        if self._thread is not None:
            self._thread.join(timeout=5)

        self._thread = None
        self._ws = None
        self._symbols.clear()

    def _run(self) -> None:
        while not self._stop_event.is_set():

            self._ws = websocket.WebSocketApp(
                self.BASE_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
            )

            self._ws.run_forever(
                ping_interval=15,
                ping_timeout=5,
            )

            if self._stop_event.is_set():
                break

            time.sleep(5)

    def _on_open(self, ws):
        self._connected.set()
        logger.info("Binance websocket connected")
        if not self._symbols:
            return

        payload = {
            "method": "SUBSCRIBE",
            "params": [
                f"{symbol.lower()}@ticker"
                for symbol in self._symbols
            ],
            "id": 1,
        }

        ws.send(json.dumps(payload))

    def _on_message(
        self,
        ws,
        message: str,
    ):
        try:
            data = json.loads(message)
        except Exception:
            return

        if "result" in data:
            return

        if "e" not in data:
            return

        if data["e"] != "24hrTicker":
            return

        ticker = {
            "exchange": "BINANCE",
            "symbol": data["s"],
            "last_price": float(data["c"]),
            "open_price": float(data["o"]),
            "high_price": float(data["h"]),
            "low_price": float(data["l"]),
            "change_percent": float(data["P"]),
            "volume": float(data["q"]),
            "event_time": data["E"],
            "raw": data,
        }

        if self._callback:
            self._callback(
                "ticker.updated",
                ticker,
            )

    def _on_error(
        self,
        ws,
        error,
    ):
        self._connected.clear()
        logger.exception("Binance websocket error: %s", error)

    def _on_close(
        self,
        ws,
        code,
        msg,
    ):
        self._connected.clear()
        logger.warning(
            "Binance websocket closed (%s): %s",
            code,
            msg,
        )

    def _on_ping(
        self,
        ws,
        message,
    ):
        pass

    def _on_pong(
        self,
        ws,
        message,
    ):
        pass



    def update_symbols(
        self,
        symbols: list[str],
    ) -> None:
        symbols = sorted(set(symbols))

        with self._lock:
            current = set(self._symbols)
            target = set(symbols)

            added = sorted(target - current)
            removed = sorted(current - target)

            self._symbols = symbols

        if not self._running:
            return

        if self._ws is None:
            return

        if not self._connected.is_set():
            return

        if added and self._connected.is_set():
            self._ws.send(json.dumps({
                "method": "SUBSCRIBE",
                "params": [
                    f"{s.lower()}@ticker"
                    for s in added
                ],
                "id": 2,
            }))

        if removed and self._connected.is_set():
            self._ws.send(json.dumps({
                "method": "UNSUBSCRIBE",
                "params": [
                    f"{s.lower()}@ticker"
                    for s in removed
                ],
                "id": 3,
            }))

    @property
    def running(self) -> bool:
        return self._running
