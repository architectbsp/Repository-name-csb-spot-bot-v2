"""
R5 restart/recovery hardening: AWAITING_LOCAL + recover_inflight_orders.
"""

from __future__ import annotations

from app.core.exchange.models import ExchangeType, OrderResult
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
    def __init__(self):
        self.execute_trade_calls = 0
        self._by_client_id: dict[str, OrderResult] = {}

    def execute_trade(self, exchange_type, trade):
        self.execute_trade_calls += 1
        cid = getattr(trade, "client_order_id", None)
        order = make_order_result(client_order_id=cid)
        if cid:
            self._by_client_id[cid] = order
        return order

    def fetch_order_by_client_id(self, exchange_type, client_order_id, symbol):
        return self._by_client_id.get(client_order_id)


class FakePositionManager:
    def __init__(self, open_symbols=None):
        self._open = set(open_symbols or [])

    def is_open(self, symbol, exchange=None):
        return symbol in self._open


def test_filled_stays_awaiting_local_until_confirm(tmp_path):
    store = tmp_path / "client_orders.json"
    exchange = TrackingExchangeManager()
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
    cid = exchange._by_client_id and next(iter(exchange._by_client_id))
    registry = ClientOrderRegistry(store)
    record = registry.get(cid)
    assert record is not None
    assert record.status == "AWAITING_LOCAL"
    active = registry.get_active_for_market("BINANCE:BTCUSDT")
    assert active is not None

    service.confirm_local_position("BINANCE:BTCUSDT")
    registry = ClientOrderRegistry(store)
    assert registry.get(cid).status == "COMPLETED"
    assert registry.get_active_for_market("BINANCE:BTCUSDT") is None


def test_recover_inflight_quarantines_unmanaged_buy_fill(tmp_path):
    store = tmp_path / "client_orders.json"
    registry = ClientOrderRegistry(store)
    cid = registry.begin_logical_trade(
        market_key="BINANCE:BTCUSDT",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        quantity="1",
    )
    registry.mark_awaiting_local(cid, exchange_order_id="ord-x")

    exchange = TrackingExchangeManager()
    exchange._by_client_id[cid] = make_order_result(
        order_id="ord-x", client_order_id=cid
    )
    service = OrderExecutionService(
        exchange,
        client_order_store_path=store,
        position_manager=FakePositionManager(),
        pending_poll_attempts=1,
    )
    findings = service.recover_inflight_orders()
    assert findings
    assert findings[0]["action"] == "quarantined_unmanaged"
    assert service.is_quarantined("BINANCE:BTCUSDT")


def test_recover_inflight_completes_when_local_position_exists(tmp_path):
    store = tmp_path / "client_orders.json"
    registry = ClientOrderRegistry(store)
    cid = registry.begin_logical_trade(
        market_key="BINANCE:BTCUSDT",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        quantity="1",
    )
    registry.mark_awaiting_local(cid, exchange_order_id="ord-x")

    exchange = TrackingExchangeManager()
    service = OrderExecutionService(
        exchange,
        client_order_store_path=store,
        position_manager=FakePositionManager(open_symbols={"BTCUSDT"}),
        pending_poll_attempts=1,
    )
    findings = service.recover_inflight_orders()
    assert findings[0]["action"] == "completed_local_confirmed"
    reloaded = ClientOrderRegistry(store)
    assert reloaded.get(cid).status == "COMPLETED"
    assert reloaded.get_active_for_market("BINANCE:BTCUSDT") is None


def test_recover_pending_fill_without_local_quarantines(tmp_path):
    store = tmp_path / "client_orders.json"
    registry = ClientOrderRegistry(store)
    cid = registry.begin_logical_trade(
        market_key="BINANCE:BTCUSDT",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        quantity="1",
    )
    # Simulate kill after submit, before ACK finalize -- still PENDING.
    exchange = TrackingExchangeManager()
    exchange._by_client_id[cid] = make_order_result(
        order_id="hidden", client_order_id=cid
    )
    service = OrderExecutionService(
        exchange,
        client_order_store_path=store,
        position_manager=FakePositionManager(),
        pending_poll_attempts=1,
    )
    findings = service.recover_inflight_orders()
    assert findings[0]["action"] == "quarantined_recovered_fill"
    assert service.is_quarantined("BINANCE:BTCUSDT")
