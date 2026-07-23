"""
Sprint 4 -- Execution pipeline: duplicate-order protection, retry policy
for transient network errors, timeout, pending-order reconciliation
(poll -> cancel-with-retry -> give up loudly) and unknown-status
handling. Every test uses interval=0 so the pending/cancel-retry paths
run instantly instead of sleeping in real time.
"""

import threading

import ccxt

from app.core.exchange.models import OrderResult
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.services.order_execution import ExecutionOutcome, OrderExecutionService
from app.core.trading.models import TradeRequest, TradeSide


def make_order_result(status: str, *, order_id: str = "order-1", filled=1.0, avg=100.0):
    return OrderResult(
        order_id=order_id,
        symbol="BTCUSDT",
        side="BUY",
        status=status,
        requested_quantity=1.0,
        filled_quantity=filled,
        average_price=avg,
        cost=filled * avg,
        raw={},
    )


def make_trade(symbol="BTCUSDT"):
    return TradeRequest(symbol=symbol, side=TradeSide.BUY, quantity=1)


class ScriptedExchangeManager:
    """Returns a scripted sequence of results/exceptions for
    execute_trade, and scripted sequences for fetch_order/cancel_order."""

    def __init__(self, execute_trade_script, fetch_order_script=None, cancel_order_script=None):
        self._execute_trade_script = list(execute_trade_script)
        self._fetch_order_script = list(fetch_order_script or [])
        self._cancel_order_script = list(cancel_order_script or [])
        self.execute_trade_calls = 0
        self.fetch_order_calls = 0
        self.cancel_order_calls = 0

    def execute_trade(self, exchange_type, trade):
        self.execute_trade_calls += 1
        outcome = self._execute_trade_script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fetch_order(self, exchange_type, order_id, symbol):
        self.fetch_order_calls += 1
        outcome = self._fetch_order_script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def cancel_order(self, exchange_type, order_id, symbol):
        self.cancel_order_calls += 1
        outcome = self._cancel_order_script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_service(exchange_manager, retry_policy=None) -> OrderExecutionService:
    return OrderExecutionService(
        exchange_manager,
        retry_policy=retry_policy,
        timeout=None,
        pending_poll_interval=0,
        pending_poll_attempts=2,
        cancel_retry_attempts=2,
    )


def test_successful_fill_returns_filled_outcome():
    exchange = ScriptedExchangeManager([make_order_result("CLOSED")])
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert result.is_filled
    assert exchange.execute_trade_calls == 1


def test_duplicate_order_for_same_symbol_is_rejected_before_reaching_exchange():
    exchange = ScriptedExchangeManager([make_order_result("CLOSED")])
    service = make_service(exchange)

    # Simulate an order already in flight for this market
    # (Sprint 18: quarantine / in-flight keys are exchange:symbol).
    service._in_flight.add("BINANCE:BTCUSDT")

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.DUPLICATE
    assert exchange.execute_trade_calls == 0


def test_in_flight_flag_is_cleared_after_execution_completes():
    exchange = ScriptedExchangeManager([make_order_result("CLOSED")])
    service = make_service(exchange)

    service.execute("BINANCE", make_trade())

    assert not service.is_in_flight("BINANCE:BTCUSDT")


def test_invalid_order_is_rejected_without_retry():
    exchange = ScriptedExchangeManager([ccxt.InvalidOrder("bad order")])
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.REJECTED
    # Not a business-rule-mandated retry case -- exactly one attempt.
    assert exchange.execute_trade_calls == 1


def test_insufficient_funds_is_retried_per_business_rules_and_can_recover():
    """docs/BUSINESS_RULES.md §8: insufficient-balance rejections are
    retried (the balance may free up, e.g. a previous sell settling)."""
    exchange = ScriptedExchangeManager(
        [ccxt.InsufficientFunds("no money"), make_order_result("CLOSED")]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2


def test_insufficient_funds_abandons_signal_after_exhausting_retries():
    exchange = ScriptedExchangeManager(
        [
            ccxt.InsufficientFunds("1"),
            ccxt.InsufficientFunds("2"),
            ccxt.InsufficientFunds("3"),
        ]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.REJECTED
    assert exchange.execute_trade_calls == 3


def test_network_error_is_retried_and_can_still_succeed():
    exchange = ScriptedExchangeManager(
        [ccxt.NetworkError("timeout"), make_order_result("CLOSED")]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2


def test_network_error_exhausting_retries_is_reported_as_network_failed():
    exchange = ScriptedExchangeManager(
        [ccxt.NetworkError("t1"), ccxt.NetworkError("t2"), ccxt.NetworkError("t3")]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.NETWORK_FAILED
    assert exchange.execute_trade_calls == 3
    assert service.is_quarantined("BINANCE:BTCUSDT")
    assert result.is_ambiguous


def test_rate_limit_429_is_retried_like_network_error():
    exchange = ScriptedExchangeManager(
        [ccxt.RateLimitExceeded("429"), make_order_result("CLOSED")]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2


def test_service_unavailable_503_is_retried_like_network_error():
    exchange = ScriptedExchangeManager(
        [ccxt.ExchangeNotAvailable("503"), make_order_result("CLOSED")]
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2


def test_buy_blocked_when_open_position_already_exists():
    from datetime import UTC, datetime

    from app.core.domain.position import Position
    from app.core.position_manager import PositionManager

    exchange = ScriptedExchangeManager([make_order_result("CLOSED")])
    service = make_service(exchange)
    pm = PositionManager()
    pm.add(
        Position(
            symbol="BTCUSDT",
            entry_price=100.0,
            quantity=1.0,
            opened_at=datetime.now(UTC),
            stop_price=90.0,
            exchange="BINANCE",
        )
    )
    service.set_position_manager(pm)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.DUPLICATE
    assert exchange.execute_trade_calls == 0


def test_pending_cancel_retries_network_error_then_succeeds():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("OPEN")],
        fetch_order_script=[make_order_result("OPEN"), make_order_result("OPEN")],
        cancel_order_script=[ccxt.NetworkError("cancel blip"), make_order_result("CANCELED")],
    )
    retry_policy = RetryPolicy(max_attempts=3, delay=0)
    service = make_service(exchange, retry_policy=retry_policy)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.TIMED_OUT
    assert exchange.cancel_order_calls == 2
    # Successful pending auto-cancel is not ambiguous -- no quarantine.
    assert not service.is_quarantined("BINANCE:BTCUSDT")
    assert not result.is_ambiguous


def test_submit_timeout_quarantines_and_invokes_ambiguous_hook():
    class TimingOutExchange:
        execute_trade_calls = 0

        def execute_trade(self, exchange_type, trade):
            self.execute_trade_calls += 1
            raise TimeoutError("submit hung")

    exchange = TimingOutExchange()
    seen: list[tuple] = []
    service = OrderExecutionService(
        exchange,
        retry_policy=RetryPolicy(max_attempts=1, delay=0),
        timeout=None,
        pending_poll_interval=0,
        pending_poll_attempts=1,
        cancel_retry_attempts=1,
        on_ambiguous=lambda market, result: seen.append((market, result.outcome)),
    )

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.TIMED_OUT
    assert result.is_ambiguous
    assert service.is_quarantined("BINANCE:BTCUSDT")
    assert seen == [("BINANCE:BTCUSDT", ExecutionOutcome.TIMED_OUT)]


def test_unexpected_exception_does_not_propagate():
    exchange = ScriptedExchangeManager([RuntimeError("boom")])
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.NETWORK_FAILED
    assert "boom" in result.error


def test_pending_order_that_fills_on_poll_is_reported_filled():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("OPEN")],
        fetch_order_script=[make_order_result("OPEN"), make_order_result("CLOSED")],
    )
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.fetch_order_calls == 2


def test_pending_order_that_never_fills_is_cancelled():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("OPEN")],
        fetch_order_script=[make_order_result("OPEN"), make_order_result("OPEN")],
        cancel_order_script=[make_order_result("CANCELED")],
    )
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.TIMED_OUT
    assert exchange.cancel_order_calls == 1


def test_pending_order_whose_cancel_also_fails_is_unreconciled():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("OPEN")],
        fetch_order_script=[make_order_result("OPEN"), make_order_result("OPEN")],
        cancel_order_script=[RuntimeError("cancel failed"), RuntimeError("cancel failed")],
    )
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.UNRECONCILED
    assert exchange.cancel_order_calls == 2


def test_unknown_status_is_never_treated_as_filled_or_rejected():
    exchange = ScriptedExchangeManager([make_order_result("SOME_WEIRD_STATUS")])
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.UNKNOWN_STATUS


def test_none_result_from_exchange_is_unknown_status():
    exchange = ScriptedExchangeManager([None])
    service = make_service(exchange)

    result = service.execute("BINANCE", make_trade())

    assert result.outcome == ExecutionOutcome.UNKNOWN_STATUS


def test_unreconciled_order_quarantines_the_symbol():
    """A symbol left UNRECONCILED must not accept any further order until
    an operator manually verifies the exchange state and clears it --
    otherwise the bot could double-buy a symbol that may already be
    filled on the exchange."""
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("OPEN"), make_order_result("CLOSED")],
        fetch_order_script=[make_order_result("OPEN"), make_order_result("OPEN")],
        cancel_order_script=[RuntimeError("cancel failed"), RuntimeError("cancel failed")],
    )
    service = make_service(exchange)

    first = service.execute("BINANCE", make_trade())
    assert first.outcome == ExecutionOutcome.UNRECONCILED
    assert service.is_quarantined("BINANCE:BTCUSDT")

    second = service.execute("BINANCE", make_trade())
    assert second.outcome == ExecutionOutcome.QUARANTINED
    # The exchange must never be contacted again for a quarantined symbol.
    assert exchange.execute_trade_calls == 1


def test_unknown_status_quarantines_the_symbol():
    exchange = ScriptedExchangeManager([make_order_result("SOME_WEIRD_STATUS")])
    service = make_service(exchange)

    service.execute("BINANCE", make_trade())

    assert service.is_quarantined("BINANCE:BTCUSDT")


def test_clear_quarantine_allows_new_orders_again():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[make_order_result("SOME_WEIRD_STATUS"), make_order_result("CLOSED")],
    )
    service = make_service(exchange)

    service.execute("BINANCE", make_trade())
    assert service.is_quarantined("BINANCE:BTCUSDT")

    cleared = service.clear_quarantine("BINANCE:BTCUSDT")
    assert cleared is True
    assert not service.is_quarantined("BINANCE:BTCUSDT")

    result = service.execute("BINANCE", make_trade())
    assert result.outcome == ExecutionOutcome.FILLED


def test_a_normal_fill_does_not_quarantine_the_symbol():
    exchange = ScriptedExchangeManager([make_order_result("CLOSED")])
    service = make_service(exchange)

    service.execute("BINANCE", make_trade())

    assert not service.is_quarantined("BINANCE:BTCUSDT")


def test_concurrent_orders_for_the_same_symbol_only_one_wins():
    """Race condition guard: two threads submitting for the same symbol
    at the same time must not both reach the exchange."""
    exchange = ScriptedExchangeManager(
        [make_order_result("CLOSED"), make_order_result("CLOSED")]
    )
    service = make_service(exchange)

    # Make the first call block just long enough for a hostile second
    # caller to try to reach the exchange too.
    release = threading.Event()
    original_execute = exchange.execute_trade

    def slow_execute(exchange_type, trade):
        release.wait(timeout=1)
        return original_execute(exchange_type, trade)

    exchange.execute_trade = slow_execute

    results = []

    def worker():
        results.append(service.execute("BINANCE", make_trade()))

    t1 = threading.Thread(target=worker)
    t1.start()

    # Give t1 a moment to register itself as in-flight before the second
    # attempt is made on the main thread.
    import time

    time.sleep(0.05)
    duplicate_result = service.execute("BINANCE", make_trade())

    release.set()
    t1.join(timeout=2)

    assert duplicate_result.outcome == ExecutionOutcome.DUPLICATE
    assert results[0].outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 1
