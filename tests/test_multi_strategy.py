"""Multi-strategy pipelines -- isolation + orchestrator fan-out."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config.settings import AppSettings
from app.core.exchange.adapter import PaperExchangeAdapter
from app.core.exchange.budgeted import (
    BudgetedExchangeManager,
    BudgetExceededError,
    MarketOrderInFlightError,
    SharedMarketOrderGate,
)
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType, OrderResult
from app.core.exchange.registry import ExchangeRegistry
from app.core.strategies.factory import (
    create_strategy,
    parse_enabled_strategies,
    supported_strategy_names,
)
from app.core.strategies.orchestrator import MultiStrategyOrchestrator
from app.core.trading.models import TradeRequest, TradeSide


def test_supported_strategies_include_four_named_lanes():
    names = supported_strategy_names()
    assert names == ["breakout", "dip_hunter", "momentum", "scalper"]


def test_create_strategy_returns_distinct_classes():
    assert create_strategy("dip_hunter").name == "dip_hunter"
    assert create_strategy("momentum").name == "momentum"
    assert create_strategy("breakout").name == "breakout"
    assert create_strategy("scalper").name == "scalper"


def test_parse_enabled_strategies_default_and_list(monkeypatch):
    monkeypatch.delenv("STRATEGIES", raising=False)
    assert parse_enabled_strategies() == ["dip_hunter"]

    monkeypatch.setenv("STRATEGIES", "dip_hunter, momentum, scalper")
    assert parse_enabled_strategies() == ["dip_hunter", "momentum", "scalper"]


def test_budgeted_exchange_manager_caps_and_debits():
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=50_000.0,
        fee_rate=0.0,
    )
    paper.set_mark_price("BTC/USDT", 100.0)
    paper.connect()
    registry = ExchangeRegistry()
    registry.register(ExchangeType.BINANCE, paper)
    inner = ExchangeManager(registry)

    budgeted = BudgetedExchangeManager(
        inner,
        initial_budget=1_000.0,
        strategy_name="scalper",
        buy_cost_buffer=0.0,
    )
    assert budgeted.get_quote_balance(ExchangeType.BINANCE) == 1_000.0

    result = budgeted.execute_trade(
        ExchangeType.BINANCE,
        TradeRequest(
            symbol="BTC/USDT",
            side=TradeSide.BUY,
            quantity=Decimal("2"),
        ),
    )
    assert isinstance(result, OrderResult)
    assert budgeted.cash == 800.0  # 2 * 100


def test_budgeted_exchange_manager_rejects_buy_over_budget():
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=50_000.0,
        fee_rate=0.0,
    )
    paper.set_mark_price("BTC/USDT", 100.0)
    paper.connect()
    registry = ExchangeRegistry()
    registry.register(ExchangeType.BINANCE, paper)
    inner = ExchangeManager(registry)

    budgeted = BudgetedExchangeManager(
        inner,
        initial_budget=150.0,
        strategy_name="scalper",
        buy_cost_buffer=0.0,
    )

    with pytest.raises(BudgetExceededError):
        budgeted.place_market_buy(ExchangeType.BINANCE, "BTC/USDT", 2.0)

    assert budgeted.cash == 150.0
    assert paper.fetch_quote_balance("USDT") == 50_000.0


def test_shared_market_order_gate_blocks_concurrent_same_market():
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=50_000.0,
        fee_rate=0.0,
    )
    paper.set_mark_price("BTC/USDT", 100.0)
    paper.connect()
    registry = ExchangeRegistry()
    registry.register(ExchangeType.BINANCE, paper)
    inner = ExchangeManager(registry)

    gate = SharedMarketOrderGate()
    assert gate.try_acquire("BINANCE:BTC/USDT") is True

    a = BudgetedExchangeManager(
        inner,
        initial_budget=5_000.0,
        strategy_name="dip_hunter",
        order_gate=gate,
        buy_cost_buffer=0.0,
    )
    with pytest.raises(MarketOrderInFlightError):
        a.place_market_buy(ExchangeType.BINANCE, "BTC/USDT", 1.0)

    gate.release("BINANCE:BTC/USDT")
    result = a.place_market_buy(ExchangeType.BINANCE, "BTC/USDT", 1.0)
    assert result.status == "CLOSED"
    assert a.cash == 4_900.0


def test_orchestrator_builds_isolated_pipelines():
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=100_000.0,
        fee_rate=0.0,
    )
    paper.connect()
    registry = ExchangeRegistry()
    registry.register(ExchangeType.BINANCE, paper)
    exchange = ExchangeManager(registry)

    orch = MultiStrategyOrchestrator()
    pipelines = orch.build(
        exchange,
        base_config=AppSettings(),
        strategy_names=["dip_hunter", "momentum"],
    )
    assert len(pipelines) == 2
    assert pipelines[0].name == "dip_hunter"
    assert pipelines[1].name == "momentum"
    assert pipelines[0].risk_manager is not pipelines[1].risk_manager
    assert pipelines[0].watch_list is not pipelines[1].watch_list
    assert pipelines[0].budget > 0
    assert pipelines[1].config.strategy.watch_percent == 3.0  # momentum preset

    ticker = SimpleNamespace(
        exchange=ExchangeType.BINANCE,
        symbol="BTC/USDT",
        last_price=100.0,
        volume_24h=1_000_000.0,
        change_24h=5.0,
        timestamp=0,
    )
    orch.handle_scan_result([ticker])
    assert pipelines[0].watch_list.contains("BINANCE:BTC/USDT")
    assert pipelines[1].watch_list.contains("BINANCE:BTC/USDT")
