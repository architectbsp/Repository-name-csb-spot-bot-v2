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


class FakeCcxtClient:
    """Minimal stand-in for ccxt's client, only implementing fetch_ohlcv."""

    def __init__(self, rows=None, error=None):
        self._rows = rows if rows is not None else []
        self._error = error
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe="15m", limit=200):
        self.calls.append((symbol, timeframe, limit))
        if self._error is not None:
            raise self._error
        return self._rows


def make_binance_exchange():
    exchange = BinanceExchange(
        ExchangeState(exchange=ExchangeType.BINANCE, enabled=True),
        ExchangeSettings(),
    )
    return exchange


def test_base_exchange_fetch_ohlcv_normalizes_ccxt_rows_into_candles():
    exchange = make_binance_exchange()
    exchange.client = FakeCcxtClient(
        rows=[
            [1_700_000_000_000, 100.0, 105.0, 95.0, 102.0, 12.5],
            [1_700_000_060_000, 102.0, 108.0, 101.0, 107.0, 8.0],
        ]
    )

    candles = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=2)

    assert exchange.client.calls == [("BTC/USDT", "1h", 2)]
    assert len(candles) == 2
    assert candles[0].timestamp == 1_700_000_000_000
    assert candles[0].open == 100.0
    assert candles[0].high == 105.0
    assert candles[0].low == 95.0
    assert candles[0].close == 102.0
    assert candles[0].volume == 12.5


def test_base_exchange_fetch_ohlcv_returns_empty_list_on_failure_instead_of_raising():
    exchange = make_binance_exchange()
    exchange.client = FakeCcxtClient(error=RuntimeError("network down"))

    candles = exchange.fetch_ohlcv("BTC/USDT")

    assert candles == []


def test_exchange_manager_fetch_ohlcv_delegates_to_the_active_exchange():
    registry = ExchangeRegistry()
    exchange = make_binance_exchange()
    exchange.client = FakeCcxtClient(
        rows=[[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 100.0]]
    )
    registry.register(ExchangeType.BINANCE, exchange)

    manager = ExchangeManager(registry)

    candles = manager.fetch_ohlcv(
        ExchangeType.BINANCE,
        "BTC/USDT",
        timeframe="5m",
        limit=1,
    )

    assert exchange.client.calls == [("BTC/USDT", "5m", 1)]
    assert len(candles) == 1
    assert candles[0].close == 1.5


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
