from types import SimpleNamespace

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
