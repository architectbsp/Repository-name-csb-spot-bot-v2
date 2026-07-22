"""
Production execution safety -- periodic reconciliation of local open
positions against the exchange's free base-asset balances.

This is the "Unknown Order Status / DB drift" complement to
OrderExecutionService's per-order pending poll: if the wallet no longer
holds enough of a coin for a recorded OPEN position (filled elsewhere,
manual sell, failed cancel that actually filled, ...), we surface
`position.reconcile_mismatch` and quarantine that market so the bot
does not pile on more orders blindly.
"""

from __future__ import annotations

import logging

from app.core.domain.position import PositionState
from app.core.exchange.market_key import market_key
from app.core.scheduler.job import Job


logger = logging.getLogger(__name__)

_RECONCILE_JOB = "position_reconciler"
_DEFAULT_INTERVAL_SECONDS = 120
# Tolerate dust / fee residuals: flag only when free base is clearly
# below the recorded position size.
_QTY_TOLERANCE = 0.95


class PositionReconciler:
    def __init__(self) -> None:
        self._exchange_manager = None
        self._position_manager = None
        self._order_execution = None
        self._event_bus = None
        self._scheduler = None
        self._initialized = False
        self._interval_seconds = _DEFAULT_INTERVAL_SECONDS

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_order_execution(self, order_execution) -> None:
        self._order_execution = order_execution

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        if self._scheduler is not None and not self._scheduler.has_job(_RECONCILE_JOB):
            job = Job(
                name=_RECONCILE_JOB,
                interval=self._interval_seconds,
                callback=self.reconcile_once,
            )
            self._scheduler.register(job)
            self._scheduler.schedule(job)

    def shutdown(self) -> None:
        self._initialized = False
        if self._scheduler is not None and self._scheduler.has_job(_RECONCILE_JOB):
            self._scheduler.unregister(_RECONCILE_JOB)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def reconcile_once(self) -> list[dict]:
        """
        Compares every OPEN local position to the free base balance on
        its exchange. Returns the list of mismatch payloads (also
        published on the event bus).
        """
        if self._exchange_manager is None or self._position_manager is None:
            return []

        mismatches: list[dict] = []

        for position in self._position_manager.get_open_positions():
            if position.state != PositionState.OPEN:
                continue
            if position.exchange is None:
                continue

            base = _base_asset(position.symbol)
            if not base:
                continue

            try:
                free = float(
                    self._exchange_manager.get_base_balance(
                        position.exchange,
                        base,
                    )
                )
            except Exception:
                logger.exception(
                    "[RECONCILE] balance fetch failed exchange=%s symbol=%s",
                    position.exchange,
                    position.symbol,
                )
                continue

            if free + 1e-12 >= position.quantity * _QTY_TOLERANCE:
                continue

            payload = {
                "symbol": position.symbol,
                "exchange": getattr(position.exchange, "name", position.exchange),
                "local_quantity": position.quantity,
                "exchange_free": free,
            }
            mismatches.append(payload)

            logger.critical(
                "[RECONCILE] Mismatch symbol=%s exchange=%s local_qty=%.8f "
                "exchange_free=%.8f -- quarantining market",
                position.symbol,
                payload["exchange"],
                position.quantity,
                free,
            )

            if self._order_execution is not None:
                key = market_key(position.exchange, position.symbol)
                self._order_execution.quarantine(key)

            if self._event_bus is not None:
                self._event_bus.publish("position.reconcile_mismatch", payload)
                self._event_bus.publish(
                    "order.needs_manual_review",
                    {
                        "symbol": position.symbol,
                        "side": "RECONCILE",
                        "outcome": "BALANCE_MISMATCH",
                        "error": (
                            f"local_qty={position.quantity} "
                            f"exchange_free={free}"
                        ),
                    },
                )

        return mismatches


def _base_asset(symbol: str) -> str | None:
    if "/" in symbol:
        return symbol.split("/", 1)[0]
    if symbol.endswith("USDT") and len(symbol) > 4:
        return symbol[:-4]
    return None
