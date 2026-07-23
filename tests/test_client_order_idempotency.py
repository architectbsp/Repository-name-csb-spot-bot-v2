"""
R5 -- ClientOrderId idempotency: retry reuse, duplicate recovery, restart.
"""

from __future__ import annotations

import ccxt

from app.core.exchange.models import ExchangeType, OrderResult
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.services.client_order_registry import ClientOrderRegistry
from app.core.services.order_execution import ExecutionOutcome, OrderExecutionService
from app.core.trading.models import TradeRequest, TradeSide


def make_order_result(
    status: str = "CLOSED",
    *,
    order_id: str = "order-1",
    filled: float = 1.0,
    client_order_id: str | None = None,
):
    raw = {}
    if client_order_id:
        raw["clientOrderId"] = client_order_id
    return OrderResult(
        order_id=order_id,
        symbol="BTCUSDT",
        side="BUY",
        status=status,
        requested_quantity=1.0,
        filled_quantity=filled,
        average_price=100.0,
        cost=filled * 100.0,
        raw=raw,
    )


class TrackingExchangeManager:
    """Records client_order_id on each submit; optional scripted outcomes."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.client_order_ids: list[str | None] = []
        self.execute_trade_calls = 0
        self._by_client_id: dict[str, OrderResult] = {}

    def execute_trade(self, exchange_type, trade):
        self.execute_trade_calls += 1
        cid = getattr(trade, "client_order_id", None)
        self.client_order_ids.append(cid)

        if self._script:
            outcome = self._script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if cid:
                self._by_client_id[cid] = outcome
            return outcome

        if cid and cid in self._by_client_id:
            raise ccxt.DuplicateOrderId(f"duplicate {cid}")

        order = make_order_result(client_order_id=cid)
        if cid:
            self._by_client_id[cid] = order
        return order

    def fetch_order_by_client_id(self, exchange_type, client_order_id, symbol):
        return self._by_client_id.get(client_order_id)

    def fetch_order(self, exchange_type, order_id, symbol):
        for order in self._by_client_id.values():
            if order.order_id == order_id:
                return order
        raise KeyError(order_id)

    def cancel_order(self, exchange_type, order_id, symbol):
        return make_order_result("CANCELED", order_id=order_id, filled=0.0)


def test_retry_reuses_same_client_order_id():
    exchange = TrackingExchangeManager(
        script=[
            ccxt.NetworkError("blip"),
            make_order_result(order_id="order-retry"),
        ]
    )
    service = OrderExecutionService(
        exchange,
        retry_policy=RetryPolicy(max_attempts=3, delay=0),
        pending_poll_attempts=1,
    )
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.BUY, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2
    assert len(exchange.client_order_ids) == 2
    assert exchange.client_order_ids[0]
    assert exchange.client_order_ids[0] == exchange.client_order_ids[1]


def test_duplicate_order_id_recovers_filled_order():
    class DupOnSecond(TrackingExchangeManager):
        def execute_trade(self, exchange_type, trade):
            self.execute_trade_calls += 1
            cid = getattr(trade, "client_order_id", None)
            self.client_order_ids.append(cid)
            if self.execute_trade_calls == 1:
                order = make_order_result(order_id="ord-a", client_order_id=cid)
                self._by_client_id[cid] = order
                raise ccxt.NetworkError("lost response")
            raise ccxt.DuplicateOrderId("already exists")

    exchange = DupOnSecond()
    service = OrderExecutionService(
        exchange,
        retry_policy=RetryPolicy(max_attempts=3, delay=0),
        pending_poll_attempts=1,
    )
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.BUY, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.FILLED
    assert result.order_result is not None
    assert result.order_result.order_id == "ord-a"
    assert exchange.client_order_ids[0] == exchange.client_order_ids[1]


def test_timeout_recovers_via_client_order_id_when_venue_filled():
    class TimeoutOnce(TrackingExchangeManager):
        def execute_trade(self, exchange_type, trade):
            self.execute_trade_calls += 1
            cid = getattr(trade, "client_order_id", None)
            self.client_order_ids.append(cid)
            order = make_order_result(order_id="hidden", client_order_id=cid)
            self._by_client_id[cid] = order
            raise TimeoutError("submit timeout")

    exchange = TimeoutOnce()
    service = OrderExecutionService(exchange, pending_poll_attempts=1)
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.BUY, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.FILLED
    assert result.order_result.order_id == "hidden"
    assert exchange.execute_trade_calls == 1


def test_timeout_without_recovery_quarantines_and_persists_ambiguous(tmp_path):
    store = tmp_path / "client_orders.json"

    class TimeoutNoFill(TrackingExchangeManager):
        def execute_trade(self, exchange_type, trade):
            self.execute_trade_calls += 1
            self.client_order_ids.append(getattr(trade, "client_order_id", None))
            raise TimeoutError("submit timeout")

        def fetch_order_by_client_id(self, exchange_type, client_order_id, symbol):
            return None

    exchange = TimeoutNoFill()
    service = OrderExecutionService(
        exchange,
        client_order_store_path=store,
        pending_poll_attempts=1,
    )
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.BUY, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.TIMED_OUT
    assert service.is_quarantined("BINANCE:BTCUSDT")

    cid = exchange.client_order_ids[0]
    registry = ClientOrderRegistry(store)
    record = registry.get(cid)
    assert record is not None
    assert record.status == "AMBIGUOUS"
    active = registry.get_active_for_market("BINANCE:BTCUSDT")
    assert active is not None
    assert active.client_order_id == cid


def test_restart_reuses_pending_client_order_id(tmp_path):
    store = tmp_path / "client_orders.json"
    registry = ClientOrderRegistry(store)
    cid = registry.begin_logical_trade(
        market_key="BINANCE:BTCUSDT",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        quantity="1",
    )
    registry.mark_ambiguous(cid)

    exchange = TrackingExchangeManager()
    exchange._by_client_id[cid] = make_order_result(
        order_id="recovered", client_order_id=cid
    )
    service = OrderExecutionService(
        exchange,
        client_order_store_path=store,
        pending_poll_attempts=1,
    )
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.BUY, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 0
    assert result.order_result.order_id == "recovered"


def test_sell_retry_reuses_client_order_id():
    exchange = TrackingExchangeManager(
        script=[
            ccxt.NetworkError("blip"),
            make_order_result(order_id="sell-1", status="CLOSED"),
        ]
    )
    service = OrderExecutionService(
        exchange,
        retry_policy=RetryPolicy(max_attempts=3, delay=0),
        pending_poll_attempts=1,
    )
    result = service.execute(
        ExchangeType.BINANCE,
        TradeRequest(symbol="BTCUSDT", side=TradeSide.SELL, quantity=1),
    )
    assert result.outcome == ExecutionOutcome.FILLED
    assert exchange.client_order_ids[0] == exchange.client_order_ids[1]


def test_registry_begin_reuses_active(tmp_path):
    store = tmp_path / "reg.json"
    reg = ClientOrderRegistry(store)
    a = reg.begin_logical_trade(
        market_key="BINANCE:ETHUSDT",
        exchange="BINANCE",
        symbol="ETHUSDT",
        side="BUY",
        quantity="2",
    )
    b = reg.begin_logical_trade(
        market_key="BINANCE:ETHUSDT",
        exchange="BINANCE",
        symbol="ETHUSDT",
        side="BUY",
        quantity="2",
    )
    assert a == b
    reg.mark_completed(a, market_key="BINANCE:ETHUSDT", exchange_order_id="x")
    c = reg.begin_logical_trade(
        market_key="BINANCE:ETHUSDT",
        exchange="BINANCE",
        symbol="ETHUSDT",
        side="BUY",
        quantity="2",
    )
    assert c != a
