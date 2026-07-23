"""
Sprint 13 -- Spot Guard + pure market-order enforcement tests.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exchange.models import ExchangeType
from app.core.exchange.spot_guard import (
    ORDER_TYPE_MARKET,
    SpotOnlyViolationException,
    assert_market_order_type,
    assert_spot_market_type,
    assert_spot_order_params,
    ensure_spot_ccxt_options,
)
from app.core.exchange.manager import ExchangeManager
from app.core.trading.models import OrderType, TradeRequest, TradeSide


def test_futures_and_margin_market_types_are_rejected():
    for forbidden in ("futures", "future", "swap", "margin", "delivery", "perp"):
        with pytest.raises(SpotOnlyViolationException):
            assert_spot_market_type(forbidden)


def test_spot_market_type_allowed():
    assert_spot_market_type("spot")
    assert_spot_market_type(None)
    assert_spot_market_type("")


def test_limit_orders_are_rejected():
    with pytest.raises(SpotOnlyViolationException):
        assert_market_order_type("limit")
    with pytest.raises(SpotOnlyViolationException):
        assert_market_order_type("LIMIT")
    assert_market_order_type(ORDER_TYPE_MARKET)
    assert_market_order_type("market")


def test_futures_params_are_rejected():
    with pytest.raises(SpotOnlyViolationException):
        assert_spot_order_params({"leverage": 5})
    with pytest.raises(SpotOnlyViolationException):
        assert_spot_order_params({"tdMode": "cross"})
    with pytest.raises(SpotOnlyViolationException):
        assert_spot_order_params({"defaultType": "futures"})


def test_ensure_spot_ccxt_options_forces_spot_and_blocks_futures():
    opts = ensure_spot_ccxt_options({})
    assert opts["defaultType"] == "spot"

    with pytest.raises(SpotOnlyViolationException):
        ensure_spot_ccxt_options({"defaultType": "futures"})


def test_trade_request_rejects_non_market_order_type():
    with pytest.raises(SpotOnlyViolationException):
        TradeRequest(
            symbol="BTC/USDT",
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            order_type="limit",  # type: ignore[arg-type]
        )


def test_trade_request_defaults_to_market():
    trade = TradeRequest(
        symbol="BTC/USDT",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
    )
    assert trade.order_type == OrderType.MARKET


def test_exchange_manager_blocks_futures_client_on_market_buy():
    """Futures/margin mode emir gönderilmeye çalışıldığında Spot Guard engeller."""
    client = SimpleNamespace(options={"defaultType": "futures"})
    exchange = SimpleNamespace(client=client, place_market_buy=MagicMock())
    registry = MagicMock()
    registry.get.return_value = exchange
    # ExchangeManager stores registry privately; build a thin stub.
    manager = ExchangeManager.__new__(ExchangeManager)
    manager._registry = SimpleNamespace(
        get=lambda _t: exchange,
        enabled=lambda: [exchange],
    )

    def _get_exchange(_type):
        return exchange

    manager._get_exchange = _get_exchange  # type: ignore[method-assign]

    with pytest.raises(SpotOnlyViolationException):
        manager.place_market_buy(ExchangeType.BINANCE, "BTC/USDT", 1.0)
    exchange.place_market_buy.assert_not_called()


def test_exchange_manager_execute_trade_uses_market_path_only():
    """Tüm alım/satım emirleri MARKET order tipiyle iletilir."""
    fills = []

    def buy(symbol, amount, params=None):
        fills.append(("BUY", symbol, amount, ORDER_TYPE_MARKET, params))
        return SimpleNamespace(status="CLOSED", filled_quantity=amount)

    def sell(symbol, amount, params=None):
        fills.append(("SELL", symbol, amount, ORDER_TYPE_MARKET, params))
        return SimpleNamespace(status="CLOSED", filled_quantity=amount)

    exchange = SimpleNamespace(
        client=SimpleNamespace(options={"defaultType": "spot"}),
        place_market_buy=buy,
        place_market_sell=sell,
    )
    manager = ExchangeManager.__new__(ExchangeManager)
    manager._get_exchange = lambda _t: exchange  # type: ignore[method-assign]

    buy_trade = TradeRequest(
        symbol="ETH/USDT",
        side=TradeSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
    )
    sell_trade = TradeRequest(
        symbol="ETH/USDT",
        side=TradeSide.SELL,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
    )

    manager.execute_trade(ExchangeType.BINANCE, buy_trade)
    manager.execute_trade(ExchangeType.BINANCE, sell_trade)

    assert fills == [
        ("BUY", "ETH/USDT", 2.0, ORDER_TYPE_MARKET, None),
        ("SELL", "ETH/USDT", 2.0, ORDER_TYPE_MARKET, None),
    ]

    with_cid = TradeRequest(
        symbol="ETH/USDT",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        client_order_id="csbtestcid001",
    )
    manager.execute_trade(ExchangeType.BINANCE, with_cid)
    assert fills[-1] == (
        "BUY",
        "ETH/USDT",
        1.0,
        ORDER_TYPE_MARKET,
        {"clientOrderId": "csbtestcid001"},
    )


def test_base_exchange_rejects_limit_helper():
    from app.core.exchange.base import BaseExchange
    from app.core.exchange.models import ConnectionStatus, ExchangeState

    class Stub(BaseExchange):
        def __init__(self):
            super().__init__(
                ExchangeState(
                    exchange=ExchangeType.BINANCE,
                    enabled=True,
                    status=ConnectionStatus.CONNECTED,
                )
            )
            self.client = SimpleNamespace(options={"defaultType": "spot"})

        def connect(self):
            return None

        def disconnect(self):
            return None

        def fetch_balance(self):
            return {}

        def fetch_markets(self):
            return {}

        def fetch_tickers(self):
            return {}

        def fetch_my_trades(self, symbol=None, limit=None):
            return []

        def get_market_metadata(self, symbol):
            raise NotImplementedError

        def normalize_amount(self, symbol, amount):
            return amount

        def normalize_price(self, symbol, price):
            return price

        def place_market_buy(self, symbol, amount):
            self._guard_spot_market_order()
            return "buy"

        def place_market_sell(self, symbol, amount):
            self._guard_spot_market_order()
            return "sell"

    stub = Stub()
    with pytest.raises(SpotOnlyViolationException):
        stub.place_limit_order("BTC/USDT", 1.0, 100.0)
    with pytest.raises(SpotOnlyViolationException):
        stub.create_order("BTC/USDT", "limit", "buy", 1.0, price=100.0)
