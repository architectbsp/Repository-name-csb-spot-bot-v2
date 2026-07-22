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

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import ccxt


logger = logging.getLogger(__name__)


class ExecutionOutcome(str, Enum):
    FILLED = "FILLED"
    # Exchange explicitly said no (insufficient funds, invalid order,
    # canceled/expired/rejected) -- retrying would be wrong.
    REJECTED = "REJECTED"
    # Transient network/connectivity failure, retries exhausted.
    NETWORK_FAILED = "NETWORK_FAILED"
    # The bounded timeout around the exchange call was exceeded.
    TIMED_OUT = "TIMED_OUT"
    # Another order for this symbol was already in flight through this
    # service; this attempt was rejected before ever reaching the
    # exchange.
    DUPLICATE = "DUPLICATE"
    # The exchange returned an order status this module does not
    # recognize as filled/open/terminal -- never guessed at, always
    # surfaced for manual review.
    UNKNOWN_STATUS = "UNKNOWN_STATUS"
    # The order stayed open past the pending-poll window AND every
    # cancel attempt also failed -- the exchange may or may not still
    # execute it. Requires manual reconciliation.
    UNRECONCILED = "UNRECONCILED"
    # The symbol is quarantined after a prior UNRECONCILED/UNKNOWN_STATUS
    # outcome; rejected before ever reaching the exchange.
    QUARANTINED = "QUARANTINED"


_KNOWN_FILLED_STATUSES = frozenset({"CLOSED", "FILLED"})
_KNOWN_OPEN_STATUSES = frozenset({"OPEN", "NEW", "PARTIALLY_FILLED"})
_KNOWN_TERMINAL_NON_FILLED_STATUSES = frozenset(
    {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}
)


@dataclass(slots=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    order_result: Any | None = None
    error: str | None = None

    @property
    def is_filled(self) -> bool:
        return self.outcome == ExecutionOutcome.FILLED


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
    ) -> None:
        self._exchange_manager = exchange_manager
        self._retry_policy = retry_policy
        self._timeout = timeout
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
        # Symbols left in an unknown/unreconciled state by a previous
        # order: we genuinely do not know whether the exchange actually
        # holds a filled position for them, so no further order is
        # allowed until an operator explicitly clears the quarantine
        # (clear_quarantine) after checking the exchange by hand.
        self._quarantined: set[str] = set()

    def is_in_flight(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._in_flight

    def is_quarantined(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._quarantined

    def clear_quarantine(self, symbol: str) -> bool:
        """For manual/operator use once the exchange state has been
        checked by hand. Returns True if the symbol was quarantined."""
        with self._lock:
            if symbol in self._quarantined:
                self._quarantined.discard(symbol)
                return True
            return False

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

        symbol = trade.symbol
        flight_key = market_key(exchange_type, symbol)

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

            if result.outcome in (
                ExecutionOutcome.UNRECONCILED,
                ExecutionOutcome.UNKNOWN_STATUS,
            ):
                self._quarantine(flight_key)
                logger.critical(
                    "[EXEC] %s is now QUARANTINED (outcome=%s) -- no "
                    "further orders for this market will be submitted "
                    "until an operator calls clear_quarantine() after "
                    "verifying the real exchange state by hand.",
                    flight_key,
                    result.outcome,
                )

            return result
        finally:
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
                    exc,
                )
                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError("unreachable")  # pragma: no cover

    def _execute_with_protection(self, exchange_type, trade) -> ExecutionResult:
        symbol = trade.symbol

        def submit():
            return self._exchange_manager.execute_trade(exchange_type, trade)

        try:
            result = self._call_exchange(submit)
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
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.InvalidOrder as exc:
            logger.error(
                "[EXEC] Order rejected by exchange symbol=%s error=%s",
                symbol,
                exc,
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.ExchangeError as exc:
            logger.error(
                "[EXEC] Exchange rejected order symbol=%s error=%s",
                symbol,
                exc,
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, error=str(exc))
        except ccxt.NetworkError as exc:
            logger.error(
                "[EXEC] Network failure submitting order (retries "
                "exhausted) symbol=%s error=%s",
                symbol,
                exc,
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.NETWORK_FAILED, error=str(exc)
            )
        except TimeoutError as exc:
            logger.error(
                "[EXEC] Timed out submitting order symbol=%s error=%s",
                symbol,
                exc,
            )
            return ExecutionResult(outcome=ExecutionOutcome.TIMED_OUT, error=str(exc))
        except Exception as exc:  # noqa: BLE001 -- never let this crash the caller
            logger.exception(
                "[EXEC] Unexpected error submitting order symbol=%s", symbol
            )
            return ExecutionResult(
                outcome=ExecutionOutcome.NETWORK_FAILED, error=str(exc)
            )

        return self._classify_result(exchange_type, trade, result)

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
            logger.warning(
                "[EXEC] Order finished without a fill symbol=%s status=%s",
                trade.symbol,
                status,
            )
            return ExecutionResult(outcome=ExecutionOutcome.REJECTED, order_result=result)

        if status in _KNOWN_OPEN_STATUSES:
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

            status = str(getattr(refreshed, "status", "") or "").upper()

            if status in _KNOWN_FILLED_STATUSES:
                return ExecutionResult(
                    outcome=ExecutionOutcome.FILLED, order_result=refreshed
                )

            if status in _KNOWN_TERMINAL_NON_FILLED_STATUSES:
                return ExecutionResult(
                    outcome=ExecutionOutcome.REJECTED, order_result=refreshed
                )

        logger.warning(
            "[EXEC] Pending order timeout symbol=%s order_id=%s -- "
            "attempting to cancel",
            symbol,
            order_id,
        )
        return self._cancel_with_retry(exchange_type, trade, result)

    def _cancel_with_retry(self, exchange_type, trade, result) -> ExecutionResult:
        order_id = getattr(result, "order_id", None)
        symbol = trade.symbol

        for attempt in range(1, self._cancel_retry_attempts + 1):
            try:
                self._exchange_manager.cancel_order(exchange_type, order_id, symbol)
                logger.info(
                    "[EXEC] Pending order cancelled symbol=%s order_id=%s",
                    symbol,
                    order_id,
                )
                return ExecutionResult(
                    outcome=ExecutionOutcome.TIMED_OUT, order_result=result
                )
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
