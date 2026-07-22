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
    """Records which exchange type get_tickers() was called with, so we
    can prove fetch_symbols() never hardcodes an exchange (isolated data
    flow, docs/BUSINESS_RULES.md §9)."""

    def __init__(self, active_type):
        self._active_type = active_type
        self.get_tickers_calls = []

    def active_exchange_type(self):
        return self._active_type

    def get_tickers(self, exchange_type):
        self.get_tickers_calls.append(exchange_type)
        return ["ticker-1", "ticker-2"]


def test_fetch_symbols_uses_the_active_exchange_dynamically():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    exchange_manager = DummyExchangeManager(ExchangeType.BYBIT)
    scanner.set_exchange(exchange_manager)

    result = scanner.fetch_symbols()

    assert result == ["ticker-1", "ticker-2"]
    assert exchange_manager.get_tickers_calls == [ExchangeType.BYBIT]


def test_fetch_symbols_follows_active_exchange_when_it_changes():
    scanner = MarketScanner()
    scanner.set_config(make_config())

    exchange_manager = DummyExchangeManager(ExchangeType.OKX)
    scanner.set_exchange(exchange_manager)

    scanner.fetch_symbols()

    exchange_manager._active_type = ExchangeType.KRAKEN
    scanner.fetch_symbols()

    assert exchange_manager.get_tickers_calls == [
        ExchangeType.OKX,
        ExchangeType.KRAKEN,
    ]
