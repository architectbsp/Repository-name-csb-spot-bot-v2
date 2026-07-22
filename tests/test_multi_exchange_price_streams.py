"""
Pure-logic tests for the non-Binance exchange price streams: symbol
formatting and raw-message-to-NormalizedTicker parsing. These never open
a real socket (start()/stop() lifecycle is covered separately), so they
run instantly and without any network access.
"""

from app.core.exchange.bybit_price_stream import BybitPriceStream
from app.core.exchange.kraken_price_stream import KrakenPriceStream
from app.core.exchange.mexc_price_stream import MEXCPriceStream
from app.core.exchange.models import ExchangeType
from app.core.exchange.okx_price_stream import OKXPriceStream


# ---------------------------------------------------------------------
# Bybit
# ---------------------------------------------------------------------

def test_bybit_wire_symbol_round_trip():
    stream = BybitPriceStream()

    assert stream._to_wire_symbol("BTC/USDT") == "BTCUSDT"
    assert stream._usdt_pair_from_compact("BTCUSDT") == "BTC/USDT"


def test_bybit_parses_ticker_message():
    stream = BybitPriceStream()

    ticker = stream._parse_ticker(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "ts": 1700000000000,
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "21109.77",
                "turnover24h": "141946527.22",
                "price24hPcnt": "0.0136",
            },
        }
    )

    assert ticker is not None
    assert ticker.exchange == ExchangeType.BYBIT
    assert ticker.symbol == "BTC/USDT"
    assert ticker.last_price == 21109.77
    assert ticker.volume_24h == 141946527.22
    assert round(ticker.change_24h, 2) == 1.36
    # docs/BUSINESS_RULES.md §9: the exact wire string must be preserved.
    assert ticker.raw_last_price == "21109.77"


def test_bybit_ignores_non_ticker_messages():
    stream = BybitPriceStream()

    assert stream._parse_ticker({"op": "pong"}) is None
    assert stream._parse_ticker({"topic": "orderbook.BTCUSDT", "data": {}}) is None


def test_bybit_uses_testnet_endpoint():
    stream = BybitPriceStream(testnet=True)
    assert stream._url == BybitPriceStream.TESTNET_URL


# ---------------------------------------------------------------------
# OKX
# ---------------------------------------------------------------------

def test_okx_wire_symbol_round_trip():
    stream = OKXPriceStream()

    assert stream._to_wire_symbol("BTC/USDT") == "BTC-USDT"
    assert stream._pair_from_dashed("BTC-USDT") == "BTC/USDT"


def test_okx_parses_ticker_message():
    stream = OKXPriceStream()

    ticker = stream._parse_ticker(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT"},
            "data": [
                {
                    "instId": "BTC-USDT",
                    "last": "21308.5",
                    "open24h": "21000.6",
                    "volCcy24h": "123456.7",
                    "ts": "1700000000000",
                }
            ],
        }
    )

    assert ticker is not None
    assert ticker.exchange == ExchangeType.OKX
    assert ticker.symbol == "BTC/USDT"
    assert ticker.last_price == 21308.5
    assert ticker.volume_24h == 123456.7
    assert ticker.change_24h > 0
    assert ticker.raw_last_price == "21308.5"


def test_okx_ignores_non_ticker_messages():
    stream = OKXPriceStream()

    assert stream._parse_ticker({"event": "subscribe"}) is None
    assert stream._parse_ticker(
        {"arg": {"channel": "books"}, "data": [{}]}
    ) is None


def test_okx_keepalive_is_raw_ping_string():
    stream = OKXPriceStream()
    assert stream._keepalive_payload() == "ping"


# ---------------------------------------------------------------------
# Kraken
# ---------------------------------------------------------------------

def test_kraken_wire_symbol_is_identity():
    stream = KrakenPriceStream()
    assert stream._to_wire_symbol("btc/usdt") == "BTC/USDT"


def test_kraken_parses_ticker_message():
    stream = KrakenPriceStream()

    ticker = stream._parse_ticker(
        {
            "channel": "ticker",
            "type": "update",
            "data": [
                {
                    "symbol": "BTC/USDT",
                    "last": 21095.4,
                    "volume": 100.0,
                    "change_pct": -1.75,
                }
            ],
        }
    )

    assert ticker is not None
    assert ticker.exchange == ExchangeType.KRAKEN
    assert ticker.symbol == "BTC/USDT"
    assert ticker.last_price == 21095.4
    # Approximated quote volume = base volume * last price.
    assert ticker.volume_24h == 100.0 * 21095.4
    assert ticker.change_24h == -1.75
    assert ticker.raw_last_price == "21095.4"


def test_kraken_ignores_non_ticker_channels():
    stream = KrakenPriceStream()

    assert stream._parse_ticker({"channel": "heartbeat"}) is None


# ---------------------------------------------------------------------
# MEXC
# ---------------------------------------------------------------------

def test_mexc_wire_symbol_round_trip():
    stream = MEXCPriceStream()

    assert stream._to_wire_symbol("BTC/USDT") == "BTCUSDT"
    assert stream._usdt_pair_from_compact("BTCUSDT") == "BTC/USDT"


def test_mexc_parses_mini_ticker_message():
    stream = MEXCPriceStream()

    ticker = stream._parse_ticker(
        {
            "c": "spot@public.miniTicker.v3.api@BTCUSDT",
            "d": {
                "s": "BTCUSDT",
                "p": "21000.00",
                "r": "0.0123",
                "tq": "12345678.90",
                "t": 1700000000000,
            },
        }
    )

    assert ticker is not None
    assert ticker.exchange == ExchangeType.MEXC
    assert ticker.symbol == "BTC/USDT"
    assert ticker.last_price == 21000.00
    assert ticker.volume_24h == 12345678.90
    assert round(ticker.change_24h, 2) == 1.23
    assert ticker.raw_last_price == "21000.00"


def test_mexc_ignores_non_ticker_messages():
    stream = MEXCPriceStream()

    assert stream._parse_ticker({"msg": "PONG"}) is None


def test_mexc_keepalive_is_ping_message():
    stream = MEXCPriceStream()
    assert stream._keepalive_payload() == {"method": "PING"}


# ---------------------------------------------------------------------
# Shared lifecycle sanity (mirrors existing BinancePriceStream tests)
# ---------------------------------------------------------------------

def test_all_streams_start_stopped_and_can_start_stop_cleanly():
    for stream in (
        BybitPriceStream(),
        OKXPriceStream(),
        KrakenPriceStream(),
        MEXCPriceStream(),
    ):
        assert stream.running is False

        stream.start([], lambda _event, _payload=None: None)
        assert stream.running is True

        stream.stop()
        assert stream.running is False
