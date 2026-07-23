from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.scheduler.scheduler import Scheduler
from app.core.security.redact import safe_error_text


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerHealth:
    """Observable runtime health for the scheduler Worker daemon."""

    active: bool
    thread_alive: bool
    error_count: int
    consecutive_errors: int
    last_error: str | None
    last_error_at: datetime | None
    last_tick_at: datetime | None


class Worker:
    def __init__(
        self,
        scheduler: Scheduler,
        interval: float = 0.1,
        *,
        on_error: Callable[[BaseException], Any] | None = None,
        on_fatal: Callable[[BaseException | None], Any] | None = None,
    ):
        self._scheduler = scheduler
        self._interval = interval
        # R1: Event stop flag is safe across Worker thread vs UI/engine stop().
        self._stop = threading.Event()
        self._active = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._on_error = on_error
        self._on_fatal = on_fatal
        self._error_count = 0
        self._consecutive_errors = 0
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None
        self._last_tick_at: datetime | None = None

    @property
    def _running(self) -> bool:
        """Backward-compat mirror of the active flag (tests / introspection)."""
        return self._active

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def health(self) -> WorkerHealth:
        with self._lock:
            return WorkerHealth(
                active=self._active,
                thread_alive=self.is_thread_alive(),
                error_count=self._error_count,
                consecutive_errors=self._consecutive_errors,
                last_error=self._last_error,
                last_error_at=self._last_error_at,
                last_tick_at=self._last_tick_at,
            )

    def is_thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._active:
            return

        self._stop.clear()
        self._active = True
        with self._lock:
            self._consecutive_errors = 0
        self._thread = threading.Thread(
            target=self._run,
            name="SchedulerWorker",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        fatal: BaseException | None = None
        try:
            while not self._stop.is_set():
                try:
                    self._scheduler.tick()
                    with self._lock:
                        self._last_tick_at = datetime.now(UTC)
                        self._consecutive_errors = 0
                except Exception as exc:
                    self._record_and_notify_error(exc)

                # Interruptible sleep so stop() does not wait a full interval.
                self._stop.wait(self._interval)
        except BaseException as exc:  # noqa: BLE001 -- surface thread death
            fatal = exc
            if not isinstance(exc, (SystemExit, KeyboardInterrupt)):
                logger.critical(
                    "[Worker] Unexpected thread failure: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
            raise
        finally:
            # Unexpected exit while still marked active = silent death risk.
            if self._active and not self._stop.is_set():
                self._active = False
                self._notify_fatal(fatal)
            elif fatal is not None and not self._stop.is_set():
                self._notify_fatal(fatal)

    def _record_and_notify_error(self, exc: BaseException) -> None:
        message = safe_error_text(exc)
        with self._lock:
            self._error_count += 1
            self._consecutive_errors += 1
            self._last_error = message
            self._last_error_at = datetime.now(UTC)
            consecutive = self._consecutive_errors
            total = self._error_count

        logger.exception(
            "[Worker] Scheduler tick failed (consecutive=%d total=%d)",
            consecutive,
            total,
        )

        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                logger.exception("[Worker] on_error callback failed")

    def _notify_fatal(self, exc: BaseException | None) -> None:
        logger.critical(
            "[Worker] Daemon terminated unexpectedly (active was True)"
        )
        if self._on_fatal is not None:
            try:
                self._on_fatal(exc)
            except Exception:
                logger.exception("[Worker] on_fatal callback failed")

    def stop(self) -> None:
        self._stop.set()
        self._active = False

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

        if thread is not None and thread is threading.current_thread():
            # Called from inside the worker (e.g. fatal→engine.stop).
            # Do not join self; clear handle so outer stop can finish.
            self._thread = None
            return

        self._thread = None
