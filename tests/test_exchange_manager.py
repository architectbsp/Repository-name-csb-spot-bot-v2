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


def test_active_exchange_type_returns_the_single_enabled_exchange():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BYBIT,
        BinanceExchange(
            ExchangeState(
                exchange=ExchangeType.BYBIT,
                enabled=True,
            ),
            ExchangeSettings(),
        ),
    )

    manager = ExchangeManager(registry)

    assert manager.active_exchange_type() == ExchangeType.BYBIT


def test_active_exchange_type_raises_when_nothing_enabled():
    manager = ExchangeManager(ExchangeRegistry())

    try:
        manager.active_exchange_type()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected RuntimeError when no exchange is enabled")


def test_binance_price_stream_start_stop():
    from app.core.exchange.binance_price_stream import BinancePriceStream

    stream = BinancePriceStream()

    assert stream.running is False


def test_binance_price_stream_preserves_raw_price_string():
    """docs/BUSINESS_RULES.md §9: the exact exchange string must survive
    untouched (Decimal/raw-string precision), not just a reformatted
    float, on the WebSocket ticker path."""
    import json

    from app.core.exchange.binance_price_stream import BinancePriceStream

    stream = BinancePriceStream()
    received = []
    stream._callback = lambda event, payload=None: received.append(payload)

    stream._on_message(
        None,
        json.dumps(
            {
                "e": "24hrTicker",
                "s": "BTCUSDT",
                "c": "1.0000088",
                "q": "250000.5",
                "P": "2.5",
                "E": 1700000000000,
            }
        ),
    )

    assert len(received) == 1
    ticker = received[0]
    assert ticker.last_price == 1.0000088
    assert ticker.raw_last_price == "1.0000088"


def test_binance_price_stream_uses_testnet_endpoint_when_configured():
    from app.core.exchange.binance_price_stream import BinancePriceStream

    stream = BinancePriceStream(testnet=True)

    assert stream._base_url == stream.TESTNET_BASE_URL

    stream.start([], lambda _: None)

    assert stream.running is True

    stream.stop()

    assert stream.running is False
