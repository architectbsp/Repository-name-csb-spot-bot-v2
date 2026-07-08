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

from types import SimpleNamespace

from app.core.watch_list import WatchList, WatchState


class DummyConfig:
    watch_percent = 3
    entry_percent = 2
    stop_loss_percent = 5
    take_profit_activation = 10
    trailing_percent = 5


class DummyPositionManager:
    def is_open(self, symbol):
        return False


def make_ticker(price, change):
    return SimpleNamespace(
        exchange="BINANCE",
        symbol="BTCUSDT",
        last_price=price,
        volume_24h=1000,
        change_24h=change,
        timestamp=0,
    )


def test_idle_starts_falling_watch():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")

    ticker = make_ticker(100, -5)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_FALLING


def test_idle_ignores_small_drop():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")

    ticker = make_ticker(100, -1)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.IDLE

