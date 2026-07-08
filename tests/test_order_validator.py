from decimal import Decimal

import pytest

from app.core.exchange.models import ExchangeType, MarketMetadata
from app.core.services.order_validator import OrderValidator
from app.core.trading.models import TradeRequest, TradeSide


class DummyExchangeManager:
    def __init__(
        self,
        *,
        active=True,
        minimum_amount=0.001,
        normalized_amount=1.0,
    ):
        self._metadata = MarketMetadata(
            symbol="BTCUSDT",
            base="BTC",
            quote="USDT",
            price_precision=0.01,
            amount_precision=0.000001,
            minimum_amount=minimum_amount,
            minimum_cost=None,
            active=active,
        )
        self._normalized_amount = normalized_amount

    def get_market_metadata(self, exchange_type, symbol):
        return self._metadata

    def normalize_amount(self, exchange_type, symbol, amount):
        return self._normalized_amount


def test_validate_returns_normalized_trade():
    validator = OrderValidator(
        DummyExchangeManager(normalized_amount=1.25)
    )

    trade = TradeRequest(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
    )

    result = validator.validate(
        ExchangeType.BINANCE,
        trade,
    )

    assert result.symbol == "BTCUSDT"
    assert result.side == TradeSide.BUY
    assert result.quantity == Decimal("1.25")


def test_inactive_market_raises():
    validator = OrderValidator(
        DummyExchangeManager(active=False)
    )

    trade = TradeRequest(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
    )

    with pytest.raises(ValueError):
        validator.validate(
            ExchangeType.BINANCE,
            trade,
        )


def test_minimum_amount_raises():
    validator = OrderValidator(
        DummyExchangeManager(
            minimum_amount=5,
            normalized_amount=1,
        )
    )

    trade = TradeRequest(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
    )

    with pytest.raises(ValueError):
        validator.validate(
            ExchangeType.BINANCE,
            trade,
        )
