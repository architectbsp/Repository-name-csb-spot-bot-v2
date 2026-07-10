from app.core.config.settings import ExchangeSettings
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.registry import ExchangeRegistry


class DummyExchange:
    def __init__(self):
        self.called = False

    def fetch_my_trades(self, symbol=None, limit=None):
        self.called = True
        return ["trade-1", "trade-2"]


def test_exchange_manager_creation():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        BinanceExchange(
            ExchangeState(
                exchange=ExchangeType.BINANCE,
                enabled=True,
            ),
            ExchangeSettings(),
        ),
    )

    manager = ExchangeManager(registry)

    assert manager.enabled()


def test_exchange_manager_price_stream():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        BinanceExchange(
            ExchangeState(
                exchange=ExchangeType.BINANCE,
                enabled=True,
            ),
            ExchangeSettings(),
        ),
    )

    manager = ExchangeManager(registry)

    assert manager.get_price_stream(
        ExchangeType.BINANCE,
    ) is not None


def test_exchange_manager_fetch_my_trades():
    registry = ExchangeRegistry()

    exchange = DummyExchange()

    registry.register(
        ExchangeType.BINANCE,
        exchange,
    )

    manager = ExchangeManager(registry)

    trades = manager.fetch_my_trades(
        ExchangeType.BINANCE,
        symbol="BTC/USDT",
        limit=10,
    )

    assert exchange.called is True
    assert trades == ["trade-1", "trade-2"]


def test_binance_price_stream_start_stop():
    from app.core.exchange.binance_price_stream import BinancePriceStream

    stream = BinancePriceStream()

    assert stream.running is False

    stream.start([], lambda _: None)

    assert stream.running is True

    stream.stop()

    assert stream.running is False
