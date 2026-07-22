from types import SimpleNamespace

from app.core.exchange.models import ExchangeType
from app.core.market_scanner import MarketScanner


def make_config():
    return SimpleNamespace(
        strategy=SimpleNamespace(
            scan_interval_seconds=5,
            min_volume_usd=100,
        )
    )


def test_lifecycle():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    scanner.initialize()

    assert scanner.is_initialized()

    scanner.start()
    assert scanner.is_running()

    scanner.stop()
    scanner.shutdown()

    assert not scanner.is_initialized()


def test_filter_symbols():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    symbols = [
        SimpleNamespace(symbol="A/USDT", volume_24h=50),
        SimpleNamespace(symbol="B/USDT", volume_24h=150),
    ]

    result = scanner.filter_symbols(symbols)

    assert len(result) == 1
    assert result[0].symbol == "B/USDT"


def test_filter_symbols_blocks_leveraged_and_blacklist():
    from app.core.services.symbol_filter import SymbolFilter

    scanner = MarketScanner()
    scanner.set_config(make_config())
    filt = SymbolFilter()
    filt.add("SCAM/USDT")
    scanner.set_symbol_filter(filt)

    symbols = [
        SimpleNamespace(symbol="BTC/USDT", volume_24h=150),
        SimpleNamespace(symbol="BTCUP/USDT", volume_24h=150),
        SimpleNamespace(symbol="ETH3L/USDT", volume_24h=150),
        SimpleNamespace(symbol="SCAM/USDT", volume_24h=150),
    ]

    result = scanner.filter_symbols(symbols)
    assert [s.symbol for s in result] == ["BTC/USDT"]


def test_filter_symbols_logs_instead_of_printing(capsys, caplog):
    """
    Regression guard for B31: filter_symbols() used to print() its
    summary directly to stdout; it must go through the module logger
    instead so it respects log level/handlers configuration.
    """
    scanner = MarketScanner()
    scanner.set_config(make_config())

    symbols = [SimpleNamespace(symbol="A/USDT", volume_24h=150)]

    with caplog.at_level("INFO", logger="app.core.market_scanner"):
        scanner.filter_symbols(symbols)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert any("fetched=1" in record.getMessage() for record in caplog.records)


class DummyExchangeManager:
    """Records which exchange types get_tickers() was called with so we
    can prove Sprint 18 scans every enabled venue (isolation rule --
    docs/BUSINESS_RULES.md §10)."""

    def __init__(self, enabled_types):
        self._enabled_types = list(enabled_types)
        self.get_tickers_calls = []

    def enabled_exchange_types(self):
        return list(self._enabled_types)

    def active_exchange_type(self):
        return self._enabled_types[0]

    def get_tickers(self, exchange_type):
        self.get_tickers_calls.append(exchange_type)
        return [f"ticker-{exchange_type.name}"]


def test_fetch_symbols_scans_every_enabled_exchange():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    exchange_manager = DummyExchangeManager(
        [ExchangeType.BINANCE, ExchangeType.BYBIT]
    )
    scanner.set_exchange(exchange_manager)

    result = scanner.fetch_symbols()

    assert result == ["ticker-BINANCE", "ticker-BYBIT"]
    assert exchange_manager.get_tickers_calls == [
        ExchangeType.BINANCE,
        ExchangeType.BYBIT,
    ]


def test_fetch_symbols_follows_enabled_set_when_it_changes():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    exchange_manager = DummyExchangeManager([ExchangeType.OKX])
    scanner.set_exchange(exchange_manager)

    scanner.fetch_symbols()

    exchange_manager._enabled_types = [ExchangeType.KRAKEN, ExchangeType.MEXC]
    scanner.fetch_symbols()

    assert exchange_manager.get_tickers_calls == [
        ExchangeType.OKX,
        ExchangeType.KRAKEN,
        ExchangeType.MEXC,
    ]
