import pytest

from app.core.config.settings import ExchangeSettings
from app.core.exchange.adapter import PaperExchangeAdapter, RealExchangeAdapter
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.bybit import BybitExchange
from app.core.exchange.factory import (
    create_exchange,
    paper_trading_enabled,
    supported_exchange_names,
)
from app.core.exchange.kraken import KrakenExchange
from app.core.exchange.mexc import MEXCExchange
from app.core.exchange.models import ExchangeType
from app.core.exchange.okx import OKXExchange


def make_settings(exchange: str) -> ExchangeSettings:
    settings = ExchangeSettings()
    settings.exchange = exchange
    return settings


@pytest.mark.parametrize(
    "name,expected_type,expected_class",
    [
        ("binance", ExchangeType.BINANCE, BinanceExchange),
        ("BYBIT", ExchangeType.BYBIT, BybitExchange),
        ("Okx", ExchangeType.OKX, OKXExchange),
        ("kraken", ExchangeType.KRAKEN, KrakenExchange),
        ("mexc", ExchangeType.MEXC, MEXCExchange),
    ],
)
def test_create_exchange_resolves_exchange_from_env_value(
    name, expected_type, expected_class, monkeypatch
):
    monkeypatch.delenv("PAPER_TRADING", raising=False)
    monkeypatch.delenv("TRADE_MODE", raising=False)

    exchange = create_exchange(make_settings(name))

    assert isinstance(exchange, RealExchangeAdapter)
    assert isinstance(exchange.live, expected_class)
    assert exchange.state.exchange == expected_type
    assert exchange.state.enabled is True

    # Requirement 3 (dynamic price stream): each exchange must ship its
    # own, already-wired PriceStream instance.
    assert exchange.get_price_stream() is not None


def test_create_exchange_paper_mode_wraps_live_venue(monkeypatch):
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.delenv("TRADE_MODE", raising=False)
    monkeypatch.setenv("PAPER_INITIAL_BALANCE", "2500")

    exchange = create_exchange(make_settings("binance"))

    assert isinstance(exchange, PaperExchangeAdapter)
    assert isinstance(exchange.live, BinanceExchange)
    assert exchange.fetch_quote_balance("USDT") == 2500.0
    assert exchange.get_price_stream() is not None


def test_paper_trading_enabled_respects_trade_mode(monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "paper")
    monkeypatch.setenv("PAPER_TRADING", "false")
    assert paper_trading_enabled() is True

    monkeypatch.setenv("TRADE_MODE", "live")
    monkeypatch.setenv("PAPER_TRADING", "true")
    assert paper_trading_enabled() is False


def test_create_exchange_rejects_unsupported_names():
    with pytest.raises(ValueError):
        create_exchange(make_settings("unknown-exchange"))


def test_supported_exchange_names_matches_business_rules():
    assert supported_exchange_names() == [
        "binance",
        "bybit",
        "kraken",
        "mexc",
        "okx",
    ]
