"""
Sprint 4 -- production-grade order execution pipeline.

Before this module, RiskManager called
`ExchangeManager.execute_trade()` directly with no protection at all:
a bare ccxt exception (network blip, exchange rejection, ...) would
propagate all the way up through Strategy/WatchList and crash whatever
thread was processing the current price tick, and nothing prevented two
overlapping calls from submitting two orders for the same symbol.

OrderExecutionService wraps every BUY/SELL submitted through RiskManager
with:
  - duplicate-order protection: a symbol can never have two orders
    in flight at once through this service.
  - a retry policy for transient network errors (never for outright
    exchange rejections -- retrying a rejected order is wrong).
  - a bounded timeout around the blocking exchange call.
  - pending-order reconciliation: market orders should fill immediately,
    but if the exchange reports one as still open (thin book / partial
    fill), this polls a bounded number of times, then tries to cancel it
    before giving up loudly.
  - unknown order status handling: an order status this module doesn't
    recognize is never silently treated as filled or unfilled -- it is
    surfaced as UNKNOWN_STATUS for manual review.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import ccxt

from app.core.services.client_order_registry import ClientOrderRegistry


logger = logging.getLogger(__name__)


class ExecutionOutcome(str, Enum):
    FILLED = "FILLED"
    # Exchange explicitly said no (insufficient funds, invalid order,
    # canceled/expired/rejected) -- retrying would be wrong.
    REJECTED = "REJECTED"
    # Transient network/connectivity failure, retries exhausted.
    NETWORK_FAILED = "NETWORK_FAILED"
    # The bounded timeout around the exchange call was exceeded, OR a
    # pending order was auto-cancelled after the poll window.
    TIMED_OUT = "TIMED_OUT"
    # Another order for this symbol was already in flight through this
    # service, OR a BUY was blocked because an OPEN local position
    # already exists for the market -- rejected before the exchange.
    DUPLICATE = "DUPLICATE"
    # The exchange returned an order status this module does not
    # recognize as filled/open/terminal -- never guessed at, always
    # surfaced for manual review.
    UNKNOWN_STATUS = "UNKNOWN_STATUS"
    # The order stayed open past the pending-poll window AND every
    # cancel attempt also failed -- the exchange may or may not still
    # execute it. Requires manual reconciliation.
    UNRECONCILED = "UNRECONCILED"
    # The symbol is quarantined after a prior ambiguous outcome;
    # rejected before ever reaching the exchange.
    QUARANTINED = "QUARANTINED"


_KNOWN_FILLED_STATUSES = frozenset({"CLOSED", "FILLED"})
_KNOWN_OPEN_STATUSES = frozenset(
    {
        "OPEN",
        "NEW",
        "PARTIALLY_FILLED",
        # Some venues surface an in-flight cancel as its own status.
        "CANCEL_PENDING",
        "PENDING_CANCEL",
    }
)
_KNOWN_TERMINAL_NON_FILLED_STATUSES = frozenset(
    {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED"}
)

_FILL_EPS = 1e-12


def _filled_quantity(order) -> float:
    try:
        return float(getattr(order, "filled_quantity", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _requested_quantity(order, trade=None) -> float:
    try:
        qty = float(getattr(order, "requested_quantity", 0.0) or 0.0)
    except (TypeError, ValueError):
        qty = 0.0
    if qty > 0:
        return qty
    if trade is not None:
        try:
            return float(getattr(trade, "quantity", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _is_fully_filled(order, trade=None) -> bool:
    filled = _filled_quantity(order)
    if filled <= _FILL_EPS:
        return False
    status = str(getattr(order, "status", "") or "").upper()
    if status in _KNOWN_FILLED_STATUSES:
        return True
    requested = _requested_quantity(order, trade)
    return requested > 0 and filled + _FILL_EPS >= requested

# Ambiguous outcomes that may mean the exchange accepted an order we
# cannot prove local state for -- quarantine until operator clears.
_QUARANTINE_OUTCOMES = frozenset(
    {
        ExecutionOutcome.UNRECONCILED,
        ExecutionOutcome.UNKNOWN_STATUS,
        ExecutionOutcome.NETWORK_FAILED,
    }
)


@dataclass(slots=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    order_result: Any | None = None
    error: str | None = None

    @property
    def is_filled(self) -> bool:
        return self.outcome == ExecutionOutcome.FILLED

    @property
    def is_ambiguous(self) -> bool:
        """True when local/exchange state may have diverged."""
        if self.outcome in _QUARANTINE_OUTCOMES:
            return True
        # Submit TimeoutError is ambiguous; pending auto-cancel success
        # returns TIMED_OUT without an error string.
        return self.outcome == ExecutionOutcome.TIMED_OUT and bool(self.error)


class OrderExecutionService:
    def __init__(
        self,
        exchange_manager,
        *,
        retry_policy=None,
        timeout=None,
        pending_poll_interval: float = 1.0,
        # ~30s pending window by default (prompt: pending order timeout).
        pending_poll_attempts: int = 30,
        cancel_retry_attempts: int = 3,
        pending_timeout_seconds: float | None = None,
        position_manager=None,
        on_ambiguous: Callable[[str, ExecutionResult], None] | None = None,
        quarantine_store_path: str | Path | None = None,
        client_order_store_path: str | Path | None = None,
    ) -> None:
        self._exchange_manager = exchange_manager
        self._retry_policy = retry_policy
        self._timeout = timeout
        self._position_manager = position_manager
        self._on_ambiguous = on_ambiguous
        self._pending_poll_interval = pending_poll_interval
        if pending_timeout_seconds is not None and pending_poll_interval > 0:
            self._pending_poll_attempts = max(
                1,
                int(pending_timeout_seconds / pending_poll_interval),
            )
        else:
            self._pending_poll_attempts = pending_poll_attempts
        self._cancel_retry_attempts = cancel_retry_attempts

        self._lock = threading.Lock()
        self._in_flight: set[str] = set()
        self._telemetry = None
        # Symbols left in an unknown/unreconciled state by a previous
        # order: we genuinely do not know whether the exchange actually
        # holds a filled position for them, so no further order is
        # allowed until an operator explicitly clears the quarantine
        # (clear_quarantine) after checking the exchange by hand.
        self._quarantined: set[str] = set()
        # R4: optional sidecar JSON so quarantine survives process restart
        # (does not touch the SQLite schema).
        self._quarantine_store_path: Path | None = (
            Path(quarantine_store_path) if quarantine_store_path else None
        )
        self._load_quarantine_store()
        # R5: durable ClientOrderId registry (JSON sidecar).
        self._client_orders = ClientOrderRegistry(client_order_store_path)

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_telemetry(self, telemetry) -> None:
        """Optional TelemetryService -- records order round-trip ms."""
        self._telemetry = telemetry

    def set_on_ambiguous(
        self, callback: Callable[[str, ExecutionResult], None] | None
    ) -> None:
        """Optional hook (e.g. PositionReconciler.reconcile_once)."""
        self._on_ambiguous = callback

    def set_quarantine_store_path(self, path: str | Path | None) -> None:
        """R4: persist quarantine set across restarts (JSON sidecar)."""
        self._quarantine_store_path = Path(path) if path else None
        self._load_quarantine_store()

    def set_client_order_store_path(self, path: str | Path | None) -> None:
        """R5: persist ClientOrderId registry across restarts (JSON sidecar)."""
        self._client_orders.set_store_path(path)

    def is_in_flight(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._in_flight

    def is_quarantined(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._quarantined

    def list_quarantined(self) -> list[str]:
        with self._lock:
            return sorted(self._quarantined)

    def clear_quarantine(self, symbol: str) -> bool:
        """For manual/operator use once the exchange state has been
        checked by hand. Returns True if the symbol was quarantined."""
        with self._lock:
            if symbol in self._quarantined:
                self._quarantined.discard(symbol)
                self._persist_quarantine_store_unlocked()
                cleared = True
            else:
                cleared = False
        # Operator verified exchange; allow a new logical ClientOrderId.
        self._client_orders.clear_market(symbol)
        return cleared

    def quarantine(self, market: str) -> None:
        """Public quarantine entry used by PositionReconciler."""
        self._quarantine(market)

    def _begin(self, symbol: str) -> ExecutionOutcome | None:
        with self._lock:
            if symbol in self._quarantined:
                return ExecutionOutcome.QUARANTINED
            if symbol in self._in_flight:
                return ExecutionOutcome.DUPLICATE
            self._in_flight.add(symbol)
            return None

    def _end(self, symbol: str) -> None:
        with self._lock:
            self._in_flight.discard(symbol)

    def _quarantine(self, symbol: str) -> None:
        with self._lock:
            self._quarantined.add(symbol)
            self._persist_quarantine_store_unlocked()

    def _load_quarantine_store(self) -> None:
        path = self._quarantine_store_path
        if path is None or not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            markets = raw.get("markets", []) if isinstance(raw, dict) else []
            with self._lock:
                self._quarantined.update(str(m) for m in markets if m)
        except Exception:
            logger.exception(
                "[EXEC] Failed loading quarantine store path=%s", path
            )

    def _persist_quarantine_store_unlocked(self) -> None:
        path = self._quarantine_store_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"markets": sorted(self._quarantined)}
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.exception(
                "[EXEC] Failed persisting quarantine store path=%s", path
            )

    def _has_open_position(self, exchange_type, symbol: str) -> bool:
        if self._position_manager is None:
            return False
        try:
            return bool(
                self._position_manager.is_open(symbol, exchange=exchange_type)
            )
        except Exception:
            logger.exception(
                "[EXEC] position_manager.is_open failed symbol=%s", symbol
            )
            return False

    def execute(self, exchange_type, trade) -> ExecutionResult:
        """
        Submits `trade` for `exchange_type`, applying every protection
        described in the module docstring. Never raises -- every
        possible outcome (including unexpected exceptions) is captured
        in the returned ExecutionResult so callers can react without
        their own try/except around the exchange call.
        """
        # Sprint 18: quarantine / in-flight keys are per (exchange, symbol)
        # so a Binance BTC order never blocks the same symbol on Bybit.
        from app.core.exchange.market_key import market_key
        from app.core.trading.models import TradeSide

        symbol = trade.symbol
        flight_key = market_key(exchange_type, symbol)
        started = time.perf_counter()

        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_market_order_type,
        )
        from app.core.trading.models import OrderType

        order_type = getattr(trade, "order_type", OrderType.MARKET)
        assert_market_order_type(
            order_type.value if hasattr(order_type, "value") else order_type
            or ORDER_TYPE_MARKET
        )

        # Duplicate BUY guard: open local position for this market.
        side = getattr(trade, "side", None)
        if side == TradeSide.BUY and self._has_open_position(exchange_type, symbol):
            logger.warning(
                "[EXEC] Duplicate BUY blocked -- open position exists "
                "symbol=%s exchange=%s",
                symbol,
                flight_key.split(":", 1)[0],
            )
            return ExecutionResult(outcome=ExecutionOutcome.DUPLICATE)

        blocked = self._begin(flight_key)

        if blocked is not None:
            logger.warning(
                "[EXEC] Order rejected before reaching the exchange: "
                "symbol=%s exchange=%s reason=%s",
                symbol,
                flight_key.split(":", 1)[0],
                blocked,
            )
            return ExecutionResult(outcome=blocked)

        try:
            result = self._execute_with_protection(exchange_type, trade)

            if result.is_ambiguous:
                self._quarantine(flight_key)
                logger.critical(
                    "[EXEC] %s is now QUARANTINED (outcome=%s) -- no "
                    "further orders for this market will be submitted "
                    "until an operator calls clear_quarantine() after "
                    "verifying the real exchange state by hand.",
                    flight_key,
                    result.outcome,
                )
                if self._on_ambiguous is not None:
                    try:
                        self._on_ambiguous(flight_key, result)
                    except Exception:
                        logger.exception(
                            "[EXEC] on_ambiguous callback failed for %s",
                            flight_key,
                        )

            return result
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if self._telemetry is not None:
                try:
                    self._telemetry.record_order_latency(elapsed_ms)
                except Exception:
                    logger.debug(
                        "[EXEC] telemetry.record_order_latency failed",
                        exc_info=True,
                    )
            self._end(flight_key)

    # docs/BUSINESS_RULES.md §8 "Insufficient Balance": retry after 1
    # minute, max 3 times, then abandon the signal -- this uses the same
    # RetryPolicy (max_attempts=3, delay=60s by default) as transient
    # network errors, since an insufficient-balance rejection can
    # legitimately resolve itself (e.g. a previous sell settling) within
    # that window. Any other exchange rejection (invalid order, generic
    # exchange error, ...) is not retried: it would not resolve itself
    # and retrying it would just resubmit a request the exchange already
    # told us is wrong.
    _RETRIABLE_EXCEPTIONS = (ccxt.NetworkError, ccxt.InsufficientFunds)

    def _call_exchange(self, operation):
        """
        Runs `operation` (optionally timeout-bounded), retrying only on
        `_RETRIABLE_EXCEPTIONS`. RetryPolicy.execute() is deliberately
        not used here because it catches every Exception type
        indiscriminately -- retrying an outright exchange rejection
        (invalid order, ...) would be wrong, so those must propagate on
        the very first attempt and be classified once by the caller.
        """
        max_attempts = (
            self._retry_policy.max_attempts() if self._retry_policy is not None else 1
        )

        for attempt in range(1, max_attempts + 1):
            try:
                if self._timeout is not None:
                    return self._timeout.wrap(operation)
                return operation()
            except self._RETRIABLE_EXCEPTIONS as exc:
                if attempt >= max_attempts:
                    raise
                delay = (
                    self._retry_policy.delay_for_attempt(attempt)
                    if self._retry_policy is not None
                    else 0
                )
                logger.warning(
                    "[EXEC] Retriable error on attempt %d/%d, retrying "
                    "in %.1fs (exponential backoff): %s",
                    attempt,
                    max_attempts,
                    delay,
                    type(exc).__name__ + f": {exc}",
                )
                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError("unreachable")  # pragma: no cover

    def _execute_with_protection(self, exchange_type, trade) -> ExecutionResult:
        from app.core.exchange.market_key import market_key

        symbol = trade.symbol
        flight_key = market_key(exchange_type, symbol)
        exchange_name = (
            exchange_type.name
            if hasattr(exchange_type, "name")
            else str(exchange_type)
        )
        side = getattr(trade, "side", None)
        side_value = side.value if hasattr(side, "value") else str(side or "")

        # R5: allocate or reuse durable ClientOrderId *before* submit.
        client_order_id = self._client_orders.begin_logical_trade(
            market_key=flight_key,
            exchange=exchange_name,
            symbol=symbol,
            side=side_value,
            quantity=getattr(trade, "quantity", ""),
        )
        trade = replace(trade, client_order_id=client_order_id)
        logger.info(
            "[EXEC] ClientOrderId bound symbol=%s exchange=%s side=%s cid=%s",
            symbol,
            exchange_name,
            side_value,
            client_order_id,
        )

        # Restart / ambiguous recovery: if the venue already has this id,
        # classify that order instead of submitting a duplicate.
        recovered = self._recover_by_client_order_id(exchange_type, trade)
        if recovered is not None:
            self._finalize_client_order(flight_key, client_order_id, recovered)
            return recovered

        def submit():
            return self._exchange_manager.execute_trade(exchange_type, trade)

        try:
            result = self._call_exchange(submit)
        except ccxt.DuplicateOrderId as exc:
            logger.warning(
                "[EXEC] DuplicateOrderId for cid=%s symbol=%s -- recovering",
                client_order_id,
                symbol,
            )
            recovered = self._recover_by_client_order_id(exchange_type, trade)
            if recovered is not None:
                self._finalize_client_order(flight_key, client_order_id, recovered)
                return recovered
            self._client_orders.mark_ambiguous(client_order_id)
            return ExecutionResult(
                outcome=ExecutionOutcome.UNRECONCILED,
                error=f"duplicate_client_order_id:{exc}",
            )
        except ccxt.InsufficientFunds as exc:
            # docs/BUSINESS_RULES.md §8: reaching this point means the 3
            # retries (1 minute apart) already happened inside
            # _call_exchange and still failed -- abandon the signal.
            logger.error(
                "[EXEC] Insufficient balance, retries exhausted symbol=%s "
                "error=%s -- abandoning signal",
                symbol,
                exc,
            )
            self._client_orders.mark_failed(
                client_order_id, market_key=flight_key
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.InvalidOrder as exc:
            logger.error(
                "[EXEC] Order rejected by exchange symbol=%s error=%s",
                symbol,
                exc,
            )
            self._client_orders.mark_failed(
                client_order_id, market_key=flight_key
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.ExchangeError as exc:
            logger.error(
                "[EXEC] Exchange rejected order symbol=%s error=%s",
                symbol,
                exc,
            )
            self._client_orders.mark_failed(
                client_order_id, market_key=flight_key
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.NetworkError as exc:
            logger.error(
                "[EXEC] Network failure submitting order (retries "
                "exhausted) symbol=%s error=%s",
                symbol,
                exc,
            )
            recovered = self._recover_by_client_order_id(exchange_type, trade)
            if recovered is not None:
                self._finalize_client_order(flight_key, client_order_id, recovered)
                return recovered
            self._client_orders.mark_ambiguous(client_order_id)
            return ExecutionResult(
                outcome=ExecutionOutcome.NETWORK_FAILED, error=str(exc)
            )
        except TimeoutError as exc:
            logger.error(
                "[EXEC] Timed out submitting order symbol=%s error=%s",
                symbol,
                exc,
            )
            recovered = self._recover_by_client_order_id(exchange_type, trade)
            if recovered is not None:
                self._finalize_client_order(flight_key, client_order_id, recovered)
                return recovered
            self._client_orders.mark_ambiguous(client_order_id)
            return ExecutionResult(outcome=ExecutionOutcome.TIMED_OUT, error=str(exc))
        except Exception as exc:  # noqa: BLE001 -- never let this crash the caller
            # Import locally to avoid a hard cycle at module import time.
            from app.core.exchange.budgeted import (
                BudgetExceededError,
                MarketOrderInFlightError,
            )

            if isinstance(exc, (BudgetExceededError, MarketOrderInFlightError)):
                logger.warning(
                    "[EXEC] Order blocked by pipeline budget/gate symbol=%s error=%s",
                    symbol,
                    exc,
                )
                self._client_orders.mark_failed(
                    client_order_id, market_key=flight_key
                )
                return ExecutionResult(
                    outcome=ExecutionOutcome.REJECTED,
                    error=str(exc),
                )

            logger.exception(
                "[EXEC] Unexpected error submitting order symbol=%s", symbol
            )
            recovered = self._recover_by_client_order_id(exchange_type, trade)
            if recovered is not None:
                self._finalize_client_order(flight_key, client_order_id, recovered)
                return recovered
            self._client_orders.mark_ambiguous(client_order_id)
            return ExecutionResult(
                outcome=ExecutionOutcome.NETWORK_FAILED, error=str(exc)
            )

        order_id = getattr(result, "order_id", None) if result is not None else None
        self._client_orders.mark_submitted(
            client_order_id, exchange_order_id=order_id
        )
        classified = self._classify_result(exchange_type, trade, result)
        self._finalize_client_order(flight_key, client_order_id, classified)
        return classified

    def _recover_by_client_order_id(
        self, exchange_type, trade
    ) -> ExecutionResult | None:
        client_order_id = getattr(trade, "client_order_id", None)
        if not client_order_id:
            return None
        fetcher = getattr(self._exchange_manager, "fetch_order_by_client_id", None)
        if not callable(fetcher):
            return None
        try:
            order = fetcher(exchange_type, client_order_id, trade.symbol)
        except Exception:
            logger.exception(
                "[EXEC] clientOrderId recovery failed symbol=%s cid=%s",
                trade.symbol,
                client_order_id,
            )
            return None
        if order is None:
            return None
        logger.warning(
            "[EXEC] Recovered order via clientOrderId symbol=%s cid=%s "
            "order_id=%s status=%s",
            trade.symbol,
            client_order_id,
            getattr(order, "order_id", None),
            getattr(order, "status", None),
        )
        return self._classify_result(exchange_type, trade, order)

    def _finalize_client_order(
        self,
        market_key: str,
        client_order_id: str,
        result: ExecutionResult,
    ) -> None:
        order_id = None
        if result.order_result is not None:
            order_id = getattr(result.order_result, "order_id", None)
        if result.outcome in {
            ExecutionOutcome.FILLED,
            ExecutionOutcome.REJECTED,
            ExecutionOutcome.DUPLICATE,
        }:
            if result.outcome == ExecutionOutcome.REJECTED:
                self._client_orders.mark_failed(
                    client_order_id, market_key=market_key
                )
            else:
                self._client_orders.mark_completed(
                    client_order_id,
                    market_key=market_key,
                    exchange_order_id=order_id,
                )
            return
        if result.is_ambiguous:
            if order_id:
                self._client_orders.mark_submitted(
                    client_order_id, exchange_order_id=order_id
                )
            self._client_orders.mark_ambiguous(client_order_id)
            return
        # Non-ambiguous terminal-ish outcomes still release the slot.
        if result.outcome in {
            ExecutionOutcome.TIMED_OUT,
        }:
            # Clean pending cancel timeout (no error) -- order gone.
            self._client_orders.mark_failed(
                client_order_id, market_key=market_key
            )
            return
        self._client_orders.mark_completed(
            client_order_id,
            market_key=market_key,
            exchange_order_id=order_id,
        )

    def _classify_result(self, exchange_type, trade, result) -> ExecutionResult:
        if result is None:
            logger.error(
                "[EXEC] No result returned from exchange for symbol=%s",
                trade.symbol,
            )
            return ExecutionResult(outcome=ExecutionOutcome.UNKNOWN_STATUS)

        status = str(getattr(result, "status", "") or "").upper()

        if status in _KNOWN_FILLED_STATUSES:
            return ExecutionResult(outcome=ExecutionOutcome.FILLED, order_result=result)

        if status in _KNOWN_TERMINAL_NON_FILLED_STATUSES:
            # Terminal cancel/reject that still shows a fill = inventory risk.
            if _filled_quantity(result) > _FILL_EPS:
                logger.critical(
                    "[EXEC] Terminal status %s with filled_qty>0 symbol=%s "
                    "-- treating as UNRECONCILED",
                    status,
                    trade.symbol,
                )
                return ExecutionResult(
                    outcome=ExecutionOutcome.UNRECONCILED,
                    order_result=result,
                    error=f"terminal_{status.lower()}_with_fill",
                )
            logger.warning(
                "[EXEC] Order finished without a fill symbol=%s status=%s",
                trade.symbol,
                status,
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, order_result=result)

        if status in _KNOWN_OPEN_STATUSES:
            if _is_fully_filled(result, trade):
                return ExecutionResult(
                    outcome=ExecutionOutcome.FILLED, order_result=result
                )
            return self._reconcile_pending_order(exchange_type, trade, result)

        logger.error(
            "[EXEC] Unknown order status symbol=%s status=%r -- treating "
            "as unresolved, needs manual review",
            trade.symbol,
            status,
        )
        return ExecutionResult(
            outcome=ExecutionOutcome.UNKNOWN_STATUS, order_result=result
        )

    def _reconcile_pending_order(self, exchange_type, trade, result) -> ExecutionResult:
        """
        Market orders are expected to fill immediately. If the exchange
        instead reports the order as still open (thin order book,
        partial fill, ...), poll a bounded number of times before
        deciding it is stuck and attempting to cancel it.
        """
        order_id = getattr(result, "order_id", None)
        symbol = trade.symbol
        latest = result

        for attempt in range(1, self._pending_poll_attempts + 1):
            time.sleep(self._pending_poll_interval)

            try:
                refreshed = self._exchange_manager.fetch_order(
                    exchange_type,
                    order_id,
                    symbol,
                )
            except Exception:
                logger.exception(
                    "[EXEC] Failed polling pending order (attempt %d/%d) "
                    "symbol=%s order_id=%s",
                    attempt,
                    self._pending_poll_attempts,
                    symbol,
                    order_id,
                )
                continue

            latest = refreshed
            status = str(getattr(refreshed, "status", "") or "").upper()

            if status in _KNOWN_FILLED_STATUSES or _is_fully_filled(refreshed, trade):
                return ExecutionResult(
                    outcome=ExecutionOutcome.FILLED, order_result=refreshed
                )

            if status in _KNOWN_TERMINAL_NON_FILLED_STATUSES:
                if _filled_quantity(refreshed) > _FILL_EPS:
                    logger.critical(
                        "[EXEC] Pending order reached terminal %s with "
                        "partial/full fill symbol=%s order_id=%s",
                        status,
                        symbol,
                        order_id,
                    )
                    return ExecutionResult(
                        outcome=ExecutionOutcome.UNRECONCILED,
                        order_result=refreshed,
                        error=f"pending_terminal_{status.lower()}_with_fill",
                    )
                return ExecutionResult(
                    outcome=ExecutionOutcome.REJECTED, order_result=refreshed
                )

        logger.warning(
            "[EXEC] Pending order timeout symbol=%s order_id=%s "
            "filled_qty=%.8f -- attempting to cancel",
            symbol,
            order_id,
            _filled_quantity(latest),
        )
        return self._cancel_with_retry(exchange_type, trade, latest)

    def _cancel_with_retry(self, exchange_type, trade, result) -> ExecutionResult:
        order_id = getattr(result, "order_id", None)
        symbol = trade.symbol

        for attempt in range(1, self._cancel_retry_attempts + 1):
            try:
                self._exchange_manager.cancel_order(exchange_type, order_id, symbol)
                logger.info(
                    "[EXEC] Pending order cancel accepted symbol=%s order_id=%s",
                    symbol,
                    order_id,
                )
                return self._verify_after_cancel(exchange_type, trade, result)
            except Exception as exc:
                delay = (
                    self._retry_policy.delay_for_attempt(attempt)
                    if self._retry_policy is not None
                    else min(8.0, 1.0 * (2 ** (attempt - 1)))
                )
                logger.error(
                    "[EXEC] Cancel attempt %d/%d failed symbol=%s "
                    "order_id=%s error=%s -- backoff %.1fs",
                    attempt,
                    self._cancel_retry_attempts,
                    symbol,
                    order_id,
                    exc,
                    delay,
                )
                if attempt < self._cancel_retry_attempts and delay > 0:
                    time.sleep(delay)

        logger.critical(
            "[EXEC] UNRECONCILED ORDER symbol=%s order_id=%s -- the "
            "exchange still shows this order open and cancellation "
            "failed %d time(s). Manual intervention required; do not "
            "assume this order is safe to ignore.",
            symbol,
            order_id,
            self._cancel_retry_attempts,
        )
        return ExecutionResult(
            outcome=ExecutionOutcome.UNRECONCILED, order_result=result
        )

    def _verify_after_cancel(
        self,
        exchange_type,
        trade,
        prior_result,
    ) -> ExecutionResult:
        """
        R4: never trust cancel alone -- re-fetch so a cancel/fill race or
        prior partial fill cannot silently leave orphan inventory.
        """
        order_id = getattr(prior_result, "order_id", None)
        symbol = trade.symbol

        try:
            refreshed = self._exchange_manager.fetch_order(
                exchange_type,
                order_id,
                symbol,
            )
        except Exception as exc:
            logger.exception(
                "[EXEC] Post-cancel fetch_order failed symbol=%s order_id=%s",
                symbol,
                order_id,
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.UNRECONCILED,
                order_result=prior_result,
                error=f"post_cancel_fetch_failed: {exc}",
            )

        status = str(getattr(refreshed, "status", "") or "").upper()
        filled = _filled_quantity(refreshed)

        if status in _KNOWN_FILLED_STATUSES or _is_fully_filled(refreshed, trade):
            logger.critical(
                "[EXEC] Cancel race: order FILLED after cancel symbol=%s "
                "order_id=%s -- returning FILLED",
                symbol,
                order_id,
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.FILLED, order_result=refreshed
            )

        if filled > _FILL_EPS:
            logger.critical(
                "[EXEC] Partial fill remains after cancel symbol=%s "
                "order_id=%s filled_qty=%.8f status=%s -- UNRECONCILED",
                symbol,
                order_id,
                filled,
                status,
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.UNRECONCILED,
                order_result=refreshed,
                error="partial_fill_after_cancel",
            )

        if status in _KNOWN_OPEN_STATUSES:
            logger.critical(
                "[EXEC] Order still open after cancel symbol=%s order_id=%s",
                symbol,
                order_id,
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.UNRECONCILED,
                order_result=refreshed,
                error="still_open_after_cancel",
            )

        if status in _KNOWN_TERMINAL_NON_FILLED_STATUSES:
            return ExecutionResult(
                outcome=ExecutionOutcome.TIMED_OUT, order_result=refreshed
            )

        logger.error(
            "[EXEC] Unknown status after cancel symbol=%s status=%r",
            symbol,
            status,
        )
        return ExecutionResult(
            outcome=ExecutionOutcome.UNKNOWN_STATUS, order_result=refreshed
        )
