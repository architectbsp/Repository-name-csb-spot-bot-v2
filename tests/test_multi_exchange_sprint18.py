"""
Sprint 18 -- simultaneous multi-exchange: composite market identity,
multi-register factory, quarantine / position isolation across venues.
"""

from datetime import UTC, datetime

from app.core.config.settings import ExchangeSettings
from app.core.domain.position import Position, PositionState
from app.core.exchange.factory import create_exchanges
from app.core.exchange.market_key import market_key, parse_market_key
from app.core.exchange.models import ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.core.exchange.manager import ExchangeManager
from app.core.position_manager import PositionManager
from app.core.services.order_execution import ExecutionOutcome, OrderExecutionService
from app.core.services.trade_journal import TradeJournal
from app.core.trading.models import TradeRequest, TradeSide
from app.core.watch_list import WatchList, WatchState

from tests.test_order_execution import ScriptedExchangeManager, make_order_result, make_service


def test_market_key_round_trip():
    key = market_key(ExchangeType.BINANCE, "BTC/USDT")
    assert key == "BINANCE:BTC/USDT"
    assert parse_market_key(key) == ("BINANCE", "BTC/USDT")


def test_create_exchanges_registers_multiple_venues(monkeypatch):
    monkeypatch.setenv("EXCHANGES", "binance,bybit")
    monkeypatch.delenv("EXCHANGE", raising=False)

    exchanges = create_exchanges()
    types = {ex.state.exchange for ex in exchanges}

    assert types == {ExchangeType.BINANCE, ExchangeType.BYBIT}


def test_create_exchanges_deduplicates_by_type(monkeypatch):
    monkeypatch.setenv("EXCHANGES", "binance,binance,bybit")

    exchanges = create_exchanges()
    types = [ex.state.exchange for ex in exchanges]

    assert types.count(ExchangeType.BINANCE) == 1
    assert ExchangeType.BYBIT in types


def test_enabled_exchange_types_lists_every_registered_venue():
    registry = ExchangeRegistry()
    for exchange_type, settings_name in (
        (ExchangeType.BINANCE, "binance"),
        (ExchangeType.OKX, "okx"),
    ):
        from app.core.exchange.factory import create_exchange

        registry.register(
            exchange_type,
            create_exchange(ExchangeSettings(exchange=settings_name)),
        )

    manager = ExchangeManager(registry)
    assert manager.enabled_exchange_types() == [
        ExchangeType.BINANCE,
        ExchangeType.OKX,
    ]
    # Back-compat shim: first enabled.
    assert manager.active_exchange_type() == ExchangeType.BINANCE


def test_position_manager_allows_same_symbol_on_two_exchanges():
    pm = PositionManager()
    now = datetime.now(UTC)

    assert pm.add(
        Position(
            symbol="BTC/USDT",
            entry_price=100.0,
            quantity=1.0,
            opened_at=now,
            exchange=ExchangeType.BINANCE,
            state=PositionState.OPEN,
        )
    )
    assert pm.add(
        Position(
            symbol="BTC/USDT",
            entry_price=101.0,
            quantity=2.0,
            opened_at=now,
            exchange=ExchangeType.BYBIT,
            state=PositionState.OPEN,
        )
    )

    assert pm.open_count() == 2
    assert pm.get("BTC/USDT", exchange=ExchangeType.BINANCE).quantity == 1.0
    assert pm.get("BTC/USDT", exchange=ExchangeType.BYBIT).quantity == 2.0
    assert pm.is_open("BTC/USDT", exchange=ExchangeType.BINANCE)
    assert pm.is_open("BTC/USDT", exchange=ExchangeType.BYBIT)


def test_watch_list_keeps_same_symbol_isolated_per_exchange():
    wl = WatchList()
    assert wl.add("ETH/USDT", exchange=ExchangeType.BINANCE)
    assert wl.add("ETH/USDT", exchange=ExchangeType.BYBIT)
    assert wl.size() == 2

    assert wl.get_state("ETH/USDT", exchange=ExchangeType.BINANCE) == WatchState.IDLE
    grouped = wl.symbols_by_exchange()
    assert grouped[ExchangeType.BINANCE] == ["ETH/USDT"]
    assert grouped[ExchangeType.BYBIT] == ["ETH/USDT"]


def test_quarantine_on_one_venue_does_not_block_another():
    exchange = ScriptedExchangeManager(
        execute_trade_script=[
            make_order_result("SOME_WEIRD_STATUS"),
            make_order_result("CLOSED"),
        ],
    )
    service = make_service(exchange)

    bad = service.execute(ExchangeType.BINANCE, TradeRequest(
        symbol="BTCUSDT", side=TradeSide.BUY, quantity=1
    ))
    assert bad.outcome == ExecutionOutcome.UNKNOWN_STATUS
    assert service.is_quarantined("BINANCE:BTCUSDT")

    ok = service.execute(ExchangeType.BYBIT, TradeRequest(
        symbol="BTCUSDT", side=TradeSide.BUY, quantity=1
    ))
    assert ok.outcome == ExecutionOutcome.FILLED
    assert exchange.execute_trade_calls == 2


def test_trade_journal_open_entries_are_per_exchange():
    journal = TradeJournal()
    journal.record_entry(
        symbol="BTC/USDT",
        exchange="BINANCE",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A",
    )
    journal.record_entry(
        symbol="BTC/USDT",
        exchange="BYBIT",
        entry_price=101.0,
        quantity=2.0,
        entry_reason="PATH_B",
    )

    assert journal.get_open("BTC/USDT", exchange="BINANCE").quantity == 1.0
    assert journal.get_open("BTC/USDT", exchange="BYBIT").quantity == 2.0

    journal.record_exit(
        "BTC/USDT",
        exit_price=110.0,
        reason="TRAILING_STOP",
        exchange="BINANCE",
    )
    assert journal.get_open("BTC/USDT", exchange="BINANCE") is None
    assert journal.get_open("BTC/USDT", exchange="BYBIT") is not None
