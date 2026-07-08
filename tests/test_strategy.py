from decimal import Decimal

from app.core.strategy import Strategy
from app.core.trading.models import TradeRequest, TradeSide


class DummyValidator:
    def validate(self, exchange, trade):
        return trade


class DummyExchangeManager:
    def execute_trade(self, exchange, trade):
        return trade


def test_create_buy_trade_request():
    strategy = Strategy()

    trade = strategy.create_trade_request(
        symbol="BTCUSDT",
        quantity=Decimal("1"),
    )

    assert isinstance(trade, TradeRequest)
    assert trade.symbol == "BTCUSDT"
    assert trade.side == TradeSide.BUY
    assert trade.quantity == Decimal("1")


def test_create_sell_trade_request():
    strategy = Strategy()

    trade = strategy.create_trade_request(
        symbol="BTCUSDT",
        quantity=Decimal("2"),
        side=TradeSide.SELL,
    )

    assert trade.side == TradeSide.SELL
    assert trade.quantity == Decimal("2")


def test_execute_trade_calls_dependencies():
    strategy = Strategy()

    strategy.set_order_validator(DummyValidator())
    strategy.set_exchange_manager(DummyExchangeManager())

    trade = strategy.create_trade_request(
        symbol="BTCUSDT",
        quantity=Decimal("1"),
    )

    result = strategy.execute_trade(
        "BINANCE",
        trade,
    )

    assert result is trade
