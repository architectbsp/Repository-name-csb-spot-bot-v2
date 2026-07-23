"""
Production execution safety -- periodic reconciliation of local open
positions against the exchange's free base-asset balances.

This is the "Unknown Order Status / DB drift" complement to
OrderExecutionService's per-order pending poll: if the wallet no longer
holds enough of a coin for a recorded OPEN position (filled elsewhere,
manual sell, failed cancel that actually filled, ...), we surface
`position.reconcile_mismatch` and quarantine that market so the bot
does not pile on more orders blindly.

R4: also probes quarantined markets with no local OPEN position for
orphan inventory (exchange free base above dust).
"""

from __future__ import annotations

import logging

from app.core.domain.position import PositionState
from app.core.exchange.market_key import market_key, parse_market_key, try_parse_exchange_type
from app.core.scheduler.job import Job


logger = logging.getLogger(__name__)

_RECONCILE_JOB = "position_reconciler"
_DEFAULT_INTERVAL_SECONDS = 120
# Tolerate dust / fee residuals: flag only when free base is clearly
# below the recorded position size.
_QTY_TOLERANCE = 0.95
# Absolute dust floor for orphan-inventory detection (no local OPEN).
_ORPHAN_DUST = 1e-8


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
        its exchange, then probes quarantined markets for orphan inventory.
        Returns the list of mismatch payloads (also published on the bus).
        """
        if self._exchange_manager is None or self._position_manager is None:
            return []

        mismatches: list[dict] = []
        mismatches.extend(self._reconcile_open_positions())
        mismatches.extend(self._reconcile_quarantined_orphans())
        return mismatches

    def _reconcile_open_positions(self) -> list[dict]:
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
                "kind": "LOCAL_GT_EXCHANGE",
                "symbol": position.symbol,
                "exchange": getattr(position.exchange, "name", position.exchange),
                "local_quantity": position.quantity,
                "exchange_free": free,
            }
            mismatches.append(payload)
            self._surface_mismatch(payload, position.exchange, position.symbol)

        return mismatches

    def _reconcile_quarantined_orphans(self) -> list[dict]:
        """
        R4: quarantined market + no local OPEN + free base above dust
        ⇒ exchange likely holds inventory the bot does not track.
        """
        if self._order_execution is None:
            return []

        list_fn = getattr(self._order_execution, "list_quarantined", None)
        if not callable(list_fn):
            return []

        mismatches: list[dict] = []
        for key in list_fn():
            try:
                ex_name, symbol = parse_market_key(key)
            except ValueError:
                continue
            exchange = try_parse_exchange_type(ex_name)
            if exchange is None:
                continue

            if self._position_manager.is_open(symbol, exchange=exchange):
                continue

            base = _base_asset(symbol)
            if not base:
                continue

            try:
                free = float(
                    self._exchange_manager.get_base_balance(exchange, base)
                )
            except Exception:
                logger.exception(
                    "[RECONCILE] orphan balance fetch failed key=%s", key
                )
                continue

            if free <= _ORPHAN_DUST:
                continue

            payload = {
                "kind": "ORPHAN_INVENTORY",
                "symbol": symbol,
                "exchange": getattr(exchange, "name", exchange),
                "local_quantity": 0.0,
                "exchange_free": free,
                "market_key": key,
            }
            mismatches.append(payload)
            self._surface_mismatch(payload, exchange, symbol, already_quarantined=True)

        return mismatches

    def _surface_mismatch(
        self,
        payload: dict,
        exchange,
        symbol: str,
        *,
        already_quarantined: bool = False,
    ) -> None:
        logger.critical(
            "[RECONCILE] Mismatch kind=%s symbol=%s exchange=%s "
            "local_qty=%s exchange_free=%s -- quarantining market",
            payload.get("kind"),
            symbol,
            payload.get("exchange"),
            payload.get("local_quantity"),
            payload.get("exchange_free"),
        )

        if self._order_execution is not None and not already_quarantined:
            key = market_key(exchange, symbol)
            self._order_execution.quarantine(key)

        if self._event_bus is not None:
            self._event_bus.publish("position.reconcile_mismatch", payload)
            self._event_bus.publish(
                "order.needs_manual_review",
                {
                    "symbol": symbol,
                    "side": "RECONCILE",
                    "outcome": payload.get("kind", "BALANCE_MISMATCH"),
                    "error": (
                        f"local_qty={payload.get('local_quantity')} "
                        f"exchange_free={payload.get('exchange_free')}"
                    ),
                },
            )


def _base_asset(symbol: str) -> str | None:
    if "/" in symbol:
        return symbol.split("/", 1)[0]
    if symbol.endswith("USDT") and len(symbol) > 4:
        return symbol[:-4]
    return None
