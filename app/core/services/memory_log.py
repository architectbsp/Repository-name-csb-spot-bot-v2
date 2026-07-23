"""
Sprint 12 -- in-memory ring buffer of recent log records for the live
bot-log panel. Attached as a logging.Handler on the root logger so every
module's logger.info/warning/... lines become available to the UI without
re-reading `logs/bot.log` from disk on every poll.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Deque

from app.core.domain.dashboard import LogRow
from app.core.services.telegram_client import redact_telegram_secrets


class MemoryLogHandler(logging.Handler):
    """Thread-safe ring buffer of the most recent log records."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self._capacity = capacity
        self._records: Deque[LogRow] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) if self.formatter else record.getMessage()
            # Strip the standard "%(asctime)s [%(levelname)s] %(name)s: "
            # prefix when a formatter already baked it in -- the UI shows
            # time / level in their own columns.
            if self.formatter is not None:
                message = record.getMessage()

            # Defense in depth: never surface Telegram bot tokens in the
            # dashboard log panel even if an upstream logger slipped.
            message = redact_telegram_secrets(message)

            row = LogRow(
                time_display=datetime.fromtimestamp(record.created).strftime(
                    "%H:%M:%S"
                ),
                level=_ui_level(record),
                message=message,
            )
            with self._lock:
                self._records.append(row)
        except Exception:
            self.handleError(record)

    def recent(self, limit: int = 40) -> list[LogRow]:
        with self._lock:
            items = list(self._records)
        if limit <= 0:
            return items
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _ui_level(record: logging.LogRecord) -> str:
    """Map a logging level (+ optional name hint) onto the small set of
    labels the bot-log panel colour-codes (INFO/TRADE/WARNING/ERROR/API)."""
    name = (record.name or "").lower()
    msg = (record.getMessage() or "").lower()

    if record.levelno >= logging.ERROR:
        return "ERROR"
    if record.levelno >= logging.WARNING:
        return "WARNING"
    if "journal" in name or "trade" in msg or "[risk]" in msg:
        return "TRADE"
    if "exchange" in name or "api" in msg or "ccxt" in name:
        return "API"
    return "INFO"


_handler: MemoryLogHandler | None = None
_handler_lock = threading.Lock()


def get_memory_log_handler(capacity: int = 200) -> MemoryLogHandler:
    """Returns the process-wide MemoryLogHandler, installing it on the
    root logger the first time it is requested."""
    global _handler

    with _handler_lock:
        if _handler is not None:
            return _handler

        handler = MemoryLogHandler(capacity=capacity)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        _handler = handler
        return handler
