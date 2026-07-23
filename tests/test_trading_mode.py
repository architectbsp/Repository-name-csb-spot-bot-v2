"""Sprint 14 -- PAPER vs REAL trading mode isolation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config.settings import ExchangeSettings
from app.core.exchange.adapter import PaperExchangeAdapter, RealExchangeAdapter
from app.core.exchange.factory import create_exchange, paper_trading_enabled
from app.core.exchange.models import ExchangeType
from app.core.exchange.trading_mode import (
    MissingRealCredentialsError,
    TradingMode,
    normalize_trading_mode,
    require_real_api_credentials,
    resolve_trading_mode,
)
from app.core.services.analytics_service import AnalyticsService
from app.core.services.trade_journal import TradeJournal


def test_normalize_aliases():
    assert normalize_trading_mode("paper") is TradingMode.PAPER
    assert normalize_trading_mode("PAPER") is TradingMode.PAPER
    assert normalize_trading_mode("live") is TradingMode.REAL
    assert normalize_trading_mode("real") is TradingMode.REAL
    assert normalize_trading_mode("production") is TradingMode.REAL


def test_resolve_trading_mode_precedence(monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "paper")
    monkeypatch.setenv("PAPER_TRADING", "false")
    assert resolve_trading_mode() is TradingMode.PAPER
    assert paper_trading_enabled() is True

    monkeypatch.setenv("TRADE_MODE", "REAL")
    monkeypatch.setenv("PAPER_TRADING", "true")
    assert resolve_trading_mode() is TradingMode.REAL
    assert paper_trading_enabled() is False

    monkeypatch.delenv("TRADE_MODE", raising=False)
    monkeypatch.setenv("PAPER_TRADING", "yes")
    assert resolve_trading_mode() is TradingMode.PAPER


def test_real_mode_requires_api_credentials(monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "REAL")
    settings = ExchangeSettings(
        exchange="binance",
        api_key="",
        api_secret="",
    )
    with pytest.raises(MissingRealCredentialsError):
        require_real_api_credentials(settings)
    with pytest.raises(MissingRealCredentialsError):
        create_exchange(settings)

    settings.api_key = "k"
    settings.api_secret = "s"
    exchange = create_exchange(settings)
    assert isinstance(exchange, RealExchangeAdapter)
    assert exchange.is_paper is False
    assert exchange.trading_mode == "REAL"


def test_paper_mode_never_calls_live_balance_or_orders(monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "PAPER")
    monkeypatch.setenv("PAPER_INITIAL_BALANCE", "1000")

    # live=None: pure paper wallet (no public-data delegation either).
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=1000.0,
        fee_rate=0.0,
    )
    paper.set_mark_price("BTC/USDT", 100.0)

    bal = paper.fetch_balance()
    assert bal["free"]["USDT"] == 1000.0

    buy = paper.place_market_buy("BTC/USDT", 1.0)
    assert buy.side == "BUY"
    sell = paper.place_market_sell("BTC/USDT", 1.0)
    assert sell.side == "SELL"
    assert paper.is_paper is True
    assert paper.trading_mode == "PAPER"


def test_paper_wrapper_never_delegates_orders_to_live(monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "PAPER")

    from app.core.exchange.models import MarketMetadata

    live = MagicMock()
    live.state = SimpleNamespace(
        exchange=ExchangeType.BINANCE,
        enabled=True,
        status=None,
        last_error=None,
    )
    live.client = None
    live.normalize_amount = lambda _s, amount: float(amount)
    live.normalize_price = lambda _s, price: float(price)
    live.get_market_metadata = lambda symbol: MarketMetadata(
        symbol=symbol,
        base="BTC",
        quote="USDT",
        price_precision=8,
        amount_precision=8,
        minimum_amount=1e-8,
        minimum_cost=1.0,
        active=True,
    )
    live.place_market_buy = MagicMock(
        side_effect=AssertionError("live buy must not run")
    )
    live.place_market_sell = MagicMock(
        side_effect=AssertionError("live sell must not run")
    )
    live.fetch_balance = MagicMock(
        side_effect=AssertionError("live balance must not run")
    )

    paper = PaperExchangeAdapter(live, initial_quote=1000.0, fee_rate=0.0)
    paper.set_mark_price("BTC/USDT", 100.0)

    paper.fetch_balance()
    live.fetch_balance.assert_not_called()
    paper.place_market_buy("BTC/USDT", 1.0)
    live.place_market_buy.assert_not_called()
    paper.place_market_sell("BTC/USDT", 1.0)
    live.place_market_sell.assert_not_called()


def test_journal_and_analytics_isolate_paper_vs_real():
    from tests.test_trade_journal import DummyTradeJournalRepository

    repo = DummyTradeJournalRepository()
    journal = TradeJournal()
    journal.set_repository(repo)
    journal.set_trading_mode("PAPER")

    journal.record_entry(
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange="BINANCE",
        trading_mode="PAPER",
    )
    journal.record_exit(
        "BTC/USDT",
        exit_price=110.0,
        reason="TRAILING_STOP",
        pnl=10.0,
        pnl_percent=10.0,
        exchange="BINANCE",
    )

    journal.set_trading_mode("REAL")
    journal.record_entry(
        symbol="ETH/USDT",
        entry_price=50.0,
        quantity=2.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange="BINANCE",
        trading_mode="REAL",
    )
    journal.record_exit(
        "ETH/USDT",
        exit_price=40.0,
        reason="STOP_LOSS",
        pnl=-20.0,
        pnl_percent=-20.0,
        exchange="BINANCE",
    )

    analytics = AnalyticsService()
    analytics.set_trade_journal(journal)

    paper_report = analytics.generate_report(trading_mode="PAPER")
    real_report = analytics.generate_report(trading_mode="REAL")

    assert paper_report.total_trades == 1
    assert paper_report.total_pnl == 10.0
    assert paper_report.trading_mode == "PAPER"

    assert real_report.total_trades == 1
    assert real_report.total_pnl == -20.0
    assert real_report.trading_mode == "REAL"
