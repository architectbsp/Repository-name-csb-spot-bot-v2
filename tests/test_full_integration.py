"""
Sprint 14 -- Full integration: E2E lifecycle, rehydrate, and leak checks.

Wires Scanner → Filter → Strategy → RiskManager (Spot Guard / MARKET) →
OrderExecution → Journal → Telemetry → Telegram against a mocked venue
and drives BUY → trailing update → partial TP → full SELL.
"""

from __future__ import annotations

import asyncio
import gc
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config.config_manager import ConfigManager
from app.core.config.settings import AppSettings, TelegramSettings
from app.core.domain.position import CloseReason, PositionState
from app.core.event_bus.event_bus import EventBus
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.market_key import market_key
from app.core.exchange.models import ExchangeType, OrderResult
from app.core.exchange.registry import ExchangeRegistry
from app.core.exchange.spot_guard import SpotOnlyViolationException
from app.core.market_scanner import MarketScanner
from app.core.persistence.service import PersistenceService
from app.core.position_manager import PositionManager
from app.core.risk_manager import RiskManager
from app.core.services.order_execution import OrderExecutionService
from app.core.services.symbol_filter import SymbolFilter
from app.core.services.telemetry_service import TelemetryService
from app.core.services.telegram_notifier import TelegramNotifier
from app.core.services.trade_journal import TradeJournal
from app.core.strategy import Strategy
from app.core.trading.models import OrderType, TradeRequest, TradeSide
from app.core.watch_list import WatchList, WatchState


SYMBOL = "BTC/USDT"
EXCHANGE = ExchangeType.BINANCE


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.reachable = True
        self.configured = True
        self.updates: list[dict] = []

    def send_message(self, text: str, *, chat_id=None, parse_mode=None) -> bool:
        self.messages.append(text)
        return True

    def get_updates(self, *, timeout: int = 0, limit: int = 20) -> list[dict]:
        batch = list(self.updates)
        self.updates.clear()
        return batch

    def probe_api_reachable(self) -> bool:
        return self.reachable

    def close(self) -> None:
        return None


class ScriptedFillExchange:
    """BUY/SELL aware mock venue; fill at ``mark_price``."""

    def __init__(self, *, mark_price: float = 100.0, balance: float = 100_000.0):
        self.mark_price = float(mark_price)
        self.balance = float(balance)
        self.executed: list[tuple] = []

    def get_quote_balance(self, exchange_type):
        return self.balance

    def active_exchange_type(self):
        return EXCHANGE

    def enabled(self):
        return [SimpleNamespace(state=SimpleNamespace(exchange=EXCHANGE))]

    def execute_trade(self, exchange_type, trade):
        self.executed.append((exchange_type, trade))
        qty = float(trade.quantity)
        fill = self.mark_price
        side = "BUY" if trade.side == TradeSide.BUY else "SELL"
        if trade.side == TradeSide.BUY:
            self.balance = max(0.0, self.balance - qty * fill)
        else:
            self.balance += qty * fill
        return OrderResult(
            order_id=f"e2e-{len(self.executed)}",
            symbol=trade.symbol,
            side=side,
            status="CLOSED",
            requested_quantity=qty,
            filled_quantity=qty,
            average_price=fill,
            cost=qty * fill,
            raw={"e2e": True},
        )


def make_config(
    *,
    watch_percent: float = 3.0,
    entry_percent: float = 2.0,
    stop_loss_percent: float = 10.0,
    trailing_activation: float = 2.0,
    trailing_percent: float = 2.5,
    partial_tp_activation: float = 5.0,
    partial_tp_sell: float = 50.0,
    min_volume_usd: float = 100.0,
):
    return SimpleNamespace(
        risk=SimpleNamespace(
            max_daily_loss_percent=50.0,
            max_open_positions=10,
            stop_loss_percent=stop_loss_percent,
            trailing_activation_percent=trailing_activation,
            trailing_percent=trailing_percent,
            max_balance_utilization_percent=99.5,
            max_volume_share_percent=0.1,
            position_sizing_mode=0,
            risk_per_trade_percent=1.0,
            atr_period=14,
            atr_multiplier=2.0,
            volatility_target_percent=0.0,
            volatility_lookback=20,
            partial_tp_activation_percent=partial_tp_activation,
            partial_tp_sell_percent=partial_tp_sell,
            kelly_fraction=0.5,
            kelly_min_trades=10,
        ),
        strategy=SimpleNamespace(
            watch_percent=watch_percent,
            entry_percent=entry_percent,
            min_volume_usd=min_volume_usd,
            max_position_hours=24,
            scan_interval_seconds=5,
            trading_hours_enabled=0,
            weekend_closed=0,
            quiet_start_hour_utc=2,
            quiet_end_hour_utc=5,
            blacklist_symbols="",
            filtered_patterns=(
                ".*UPUSDT$,.*DOWNUSDT$,.*3LUSDT$,.*3SUSDT$,BEAR.*,BULL.*"
            ),
        ),
    )


def make_ticker(
    price: float,
    *,
    change_24h: float = 0.0,
    volume_24h: float = 5_000_000.0,
):
    return SimpleNamespace(
        exchange=EXCHANGE,
        symbol=SYMBOL,
        last_price=price,
        change_24h=change_24h,
        volume_24h=volume_24h,
        raw_last_price=f"{price:.8f}",
        timestamp=int(datetime.now(UTC).timestamp() * 1000),
    )


def wire_pipeline(exchange, config, *, persistence: PersistenceService | None = None):
    """Hand-wired BotEngine pipeline (no live network / scheduler)."""
    bus = EventBus()
    symbol_filter = SymbolFilter()
    if hasattr(config, "filter"):
        symbol_filter.set_config(config)

    scanner = MarketScanner()
    scanner.set_config(config)
    scanner.set_symbol_filter(symbol_filter)

    positions = PositionManager()
    positions.set_config(config)
    journal = TradeJournal()
    telemetry = TelemetryService()
    telemetry.set_exchange_manager(exchange)
    telemetry.set_market_scanner(scanner)

    if persistence is not None:
        positions.set_repository(persistence.position_repository())
        journal.set_repository(persistence.trade_journal_repository())
    else:
        # In-memory repo so CLOSED rows remain queryable after exit
        # (TradeJournal.query without a repo cannot see closed entries).
        from tests.test_trade_journal import DummyTradeJournalRepository

        journal.set_repository(DummyTradeJournalRepository())

    rm = RiskManager()
    rm.set_config(config)
    rm.set_exchange_manager(exchange)
    rm.set_order_validator(SimpleNamespace(validate=lambda _e, trade: trade))
    rm.set_position_manager(positions)
    rm.set_trade_journal(journal)
    rm.set_event_bus(bus)
    rm.set_symbol_filter(symbol_filter)
    rm.set_telemetry(telemetry)
    oes = OrderExecutionService(
        exchange,
        pending_poll_interval=0,
        pending_poll_attempts=1,
    )
    oes.set_position_manager(positions)
    oes.set_telemetry(telemetry)
    rm._order_execution = oes

    strategy = Strategy()
    strategy.set_config(config)
    strategy.set_risk_manager(rm)
    strategy.set_position_manager(positions)
    strategy.set_trade_journal(journal)

    watch_list = WatchList()
    watch_list.set_strategy(strategy)
    watch_list.set_config(config)

    tg_client = FakeTelegramClient()
    notifier = TelegramNotifier(tg_client)
    tg_settings = AppSettings()
    tg_settings.telegram = TelegramSettings(
        bot_token="token",
        chat_id="123",
        admin_chat_id="123",
        enabled=True,
        daily_summary_hour_utc=0,
        weekly_summary_weekday=0,
        connectivity_probe_seconds=30,
    )
    notifier.set_config(tg_settings)
    notifier.set_event_bus(bus)
    notifier.set_trade_journal(journal)
    notifier.set_risk_manager(rm)
    notifier.set_position_manager(positions)
    notifier.set_exchange_manager(exchange)

    bus.subscribe("position.closed", positions.handle_position_closed)
    bus.subscribe("position.closed", watch_list.handle_position_closed)

    for module in (scanner, positions, rm, strategy, watch_list):
        module.initialize()
        module.start()
    notifier.initialize()

    return SimpleNamespace(
        bus=bus,
        scanner=scanner,
        symbol_filter=symbol_filter,
        watch_list=watch_list,
        strategy=strategy,
        risk=rm,
        positions=positions,
        journal=journal,
        telemetry=telemetry,
        order_execution=oes,
        telegram=notifier,
        telegram_client=tg_client,
        exchange=exchange,
        config=config,
        persistence=persistence,
    )


def shutdown_pipeline(pipe) -> None:
    pipe.telegram.shutdown()
    for module in (
        pipe.scanner,
        pipe.watch_list,
        pipe.positions,
        pipe.risk,
        pipe.strategy,
    ):
        module.stop()
        module.shutdown()

    # Release DB sessions so the pool reports zero checked-out connections.
    for holder in (pipe.positions, pipe.journal):
        repo = getattr(holder, "_repository", None)
        session = getattr(repo, "_session", None) if repo is not None else None
        if session is not None:
            session.close()


def seed_via_scanner_and_path_b(pipe, *, entry_price: float = 106.0) -> None:
    """Scanner → Filter → WatchList, then Path B recovery → BUY."""
    candidates = [
        SimpleNamespace(
            symbol=SYMBOL,
            volume_24h=5_000_000.0,
            exchange=EXCHANGE,
            last_price=100.0,
            change_24h=-5.0,
        ),
        SimpleNamespace(
            symbol="BTCUP/USDT",
            volume_24h=5_000_000.0,
            exchange=EXCHANGE,
        ),
        SimpleNamespace(
            symbol="SCAM/USDT",
            volume_24h=5_000_000.0,
            exchange=EXCHANGE,
        ),
    ]
    pipe.symbol_filter.add("SCAM/USDT")
    filtered = pipe.scanner.filter_symbols(candidates)
    assert [c.symbol for c in filtered] == [SYMBOL]

    pipe.watch_list.handle_scan_result(filtered)
    key = market_key(EXCHANGE, SYMBOL)
    assert pipe.watch_list.contains(key) or pipe.watch_list.contains(SYMBOL)

    # Drive Path B: falling → rising → recovery past entry_percent.
    pipe.strategy.on_ticker(pipe.watch_list, make_ticker(100.0, change_24h=-5.0))
    assert pipe.watch_list.get_state(key) == WatchState.WATCH_FALLING

    # Price must rise above the recorded lowest to leave WATCH_FALLING.
    pipe.strategy.on_ticker(pipe.watch_list, make_ticker(101.0, change_24h=-4.0))
    assert pipe.watch_list.get_state(key) == WatchState.WATCH_RISING

    pipe.exchange.mark_price = entry_price
    pipe.strategy.on_ticker(
        pipe.watch_list,
        make_ticker(entry_price, change_24h=6.0),
    )
    assert pipe.watch_list.get_state(key) == WatchState.POSITION_OPEN
    assert pipe.positions.is_open(SYMBOL, exchange=EXCHANGE)


# ---------------------------------------------------------------------------
# 1. End-to-end BUY → trailing → partial TP → full SELL
# ---------------------------------------------------------------------------


def test_e2e_buy_trailing_partial_tp_full_sell():
    exchange = ScriptedFillExchange(mark_price=100.0)
    config = make_config()
    pipe = wire_pipeline(exchange, config)

    seed_via_scanner_and_path_b(pipe, entry_price=106.0)
    position = pipe.positions.get(SYMBOL, exchange=EXCHANGE)
    assert position is not None
    assert position.state == PositionState.OPEN
    entry = position.entry_price
    assert abs(entry - 106.0) < 1e-9

    open_journal = pipe.journal.get_open(SYMBOL, exchange=EXCHANGE)
    assert open_journal is not None
    assert "PATH_B" in (open_journal.entry_reason or "")

    assert any("BUY" in m.upper() or "OPEN" in m.upper() for m in pipe.telegram_client.messages)
    buy_count = sum(1 for _, t in exchange.executed if t.side == TradeSide.BUY)
    assert buy_count == 1
    assert all(t.order_type == OrderType.MARKET for _, t in exchange.executed)

    # Trailing activation (+2%) before partial TP (+5%).
    trail_tick = entry * 1.03  # +3%
    exchange.mark_price = trail_tick
    pipe.risk.on_price_tick(make_ticker(trail_tick))
    assert position.stop_stage == "TRAILING"
    expected_trail = trail_tick * (1.0 - config.risk.trailing_percent / 100.0)
    assert abs(position.stop_price - expected_trail) < 1e-9
    assert position.partial_exits_taken == 0
    assert position.state == PositionState.OPEN

    # Partial TP at +10%.
    partial_tick = entry * 1.10
    exchange.mark_price = partial_tick
    qty_before = position.quantity
    pipe.risk.on_price_tick(make_ticker(partial_tick))
    assert position.partial_exits_taken == 1
    assert abs(position.quantity - qty_before * 0.5) < 1e-9
    assert position.state == PositionState.OPEN
    assert position.stop_stage == "TRAILING"
    assert any(
        "PARTIAL" in m.upper() for m in pipe.telegram_client.messages
    )

    # Dump through trailing stop → full SELL.
    crash = position.stop_price * 0.99
    exchange.mark_price = crash
    pipe.risk.on_price_tick(make_ticker(crash))
    assert not pipe.positions.is_open(SYMBOL, exchange=EXCHANGE)
    assert position.state == PositionState.CLOSED
    assert position.close_reason in {
        CloseReason.TRAILING_STOP,
        "TRAILING_STOP",
        CloseReason.TRAILING_STOP.value,
    }

    closed = pipe.journal.query(symbol=SYMBOL, status="CLOSED", limit=5)
    assert closed
    assert closed[0].exit_reason in {"TRAILING_STOP", CloseReason.TRAILING_STOP.value}

    snap = pipe.telemetry.collect()
    assert snap.order_latency_ms is not None and snap.order_latency_ms >= 0

    sell_sides = [t.side for _, t in exchange.executed if t.side == TradeSide.SELL]
    assert len(sell_sides) >= 2  # partial + full

    shutdown_pipeline(pipe)


def test_e2e_spot_guard_via_exchange_manager_market_buy_ok():
    """Valid MARKET spot buy through ExchangeManager + paper adapter."""
    from decimal import Decimal

    from app.core.exchange.adapter import PaperExchangeAdapter

    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=EXCHANGE,
        initial_quote=10_000.0,
        fee_rate=0.0,
        slippage_bps=0,
    )
    paper.connect()
    paper.set_mark_price(SYMBOL, 100.0)
    registry = ExchangeRegistry()
    registry.register(EXCHANGE, paper)
    manager = ExchangeManager(registry)

    ok = manager.execute_trade(
        EXCHANGE,
        TradeRequest(
            symbol=SYMBOL,
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
        ),
    )
    assert ok.status == "CLOSED"
    assert ok.side == "BUY"


def test_e2e_spot_guard_rejects_futures_params():
    from decimal import Decimal

    from app.core.exchange.adapter import PaperExchangeAdapter
    from app.core.exchange.spot_guard import assert_spot_order_params

    with pytest.raises(SpotOnlyViolationException):
        assert_spot_order_params({"leverage": 5})

    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=EXCHANGE,
        initial_quote=5_000.0,
    )
    paper.connect()
    paper.set_mark_price(SYMBOL, 50.0)
    registry = ExchangeRegistry()
    registry.register(EXCHANGE, paper)
    manager = ExchangeManager(registry)

    # TradeRequest is frozen+slots; ExchangeManager reads getattr(trade, "params").
    trade = SimpleNamespace(
        symbol=SYMBOL,
        side=TradeSide.BUY,
        quantity=Decimal("0.1"),
        order_type=OrderType.MARKET,
        params={"tdMode": "cross"},
    )
    with pytest.raises(SpotOnlyViolationException):
        manager.execute_trade(EXCHANGE, trade)


# ---------------------------------------------------------------------------
# 2. Graceful shutdown & rehydrate + leak checks
# ---------------------------------------------------------------------------


def test_graceful_shutdown_and_rehydrate(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'sprint14.db'}"
    persistence = PersistenceService.from_url(db_url)
    exchange = ScriptedFillExchange(mark_price=100.0)
    config = make_config()
    pipe = wire_pipeline(exchange, config, persistence=persistence)

    seed_via_scanner_and_path_b(pipe, entry_price=106.0)
    position = pipe.positions.get(SYMBOL, exchange=EXCHANGE)
    assert position is not None
    entry = position.entry_price
    open_id = pipe.journal.get_open(SYMBOL, exchange=EXCHANGE).id

    # Raise trailing before "crash" so rehydrate resumes mid-lifecycle.
    trail_tick = entry * 1.04
    exchange.mark_price = trail_tick
    pipe.risk.on_price_tick(make_ticker(trail_tick))
    assert position.stop_stage == "TRAILING"
    stop_before = position.stop_price
    highest_before = position.highest_price

    shutdown_pipeline(pipe)
    assert not pipe.risk.is_initialized()
    assert pipe.positions.open_count() == 0  # cleared from memory

    # --- Restart: new modules, same SQLite ---
    persistence2 = PersistenceService.from_url(db_url)
    exchange2 = ScriptedFillExchange(mark_price=trail_tick, balance=exchange.balance)
    pipe2 = wire_pipeline(exchange2, config, persistence=persistence2)

    restored_rows = persistence2.load_positions()
    assert len(restored_rows) == 1
    for row in restored_rows:
        assert pipe2.positions.restore(row)

    loaded = pipe2.journal.load_open_entries()
    assert loaded == 1
    restored = pipe2.positions.get(SYMBOL, exchange=EXCHANGE)
    assert restored is not None
    assert restored.state == PositionState.OPEN
    assert restored.stop_stage == "TRAILING"
    assert abs(restored.stop_price - stop_before) < 1e-9
    assert abs(restored.highest_price - highest_before) < 1e-9
    assert pipe2.journal.get_open(SYMBOL, exchange=EXCHANGE).id == open_id

    # Resume: partial TP then trail exit.
    partial_tick = entry * 1.10
    exchange2.mark_price = partial_tick
    pipe2.risk.on_price_tick(make_ticker(partial_tick))
    assert restored.partial_exits_taken == 1

    crash = restored.stop_price * 0.99
    exchange2.mark_price = crash
    pipe2.risk.on_price_tick(make_ticker(crash))
    assert not pipe2.positions.is_open(SYMBOL, exchange=EXCHANGE)
    closed = pipe2.journal.query(symbol=SYMBOL, status="CLOSED", limit=1)
    assert closed
    assert closed[0].exit_reason in {"TRAILING_STOP", CloseReason.TRAILING_STOP.value}

    shutdown_pipeline(pipe2)
    persistence.engine.dispose()
    persistence2.engine.dispose()


def test_config_manager_singleton_reconfigure_after_reset(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config.settings_store import SettingsStore
    from app.core.persistence.database import Base
    from app.core.persistence.repository import SettingsRepository

    ConfigManager.reset_instance()
    engine = create_engine(f"sqlite:///{tmp_path / 'cfg.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, future=True)()
    store = SettingsStore(SettingsRepository(session))
    settings = AppSettings()
    store.load_into(settings)
    bus = EventBus()
    mgr = ConfigManager.instance()
    mgr.configure(settings, store, bus, json_path=tmp_path / "config.json")
    errors = mgr.save({"watch_pct": 4.0}, source="sprint14")
    assert errors == []
    assert settings.strategy.watch_percent == 4.0

    first = ConfigManager.instance()
    ConfigManager.reset_instance()
    second = ConfigManager.instance()
    assert first is not second

    settings2 = AppSettings()
    store2 = SettingsStore(
        SettingsRepository(sessionmaker(bind=engine, future=True)())
    )
    store2.load_into(settings2)
    second.configure(settings2, store2, EventBus())
    assert settings2.strategy.watch_percent == 4.0
    engine.dispose()


def test_no_asyncio_task_or_db_pool_leak_after_shutdown(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'leak.db'}"
    persistence = PersistenceService.from_url(db_url)
    exchange = ScriptedFillExchange()
    pipe = wire_pipeline(exchange, make_config(), persistence=persistence)
    seed_via_scanner_and_path_b(pipe, entry_price=106.0)

    # Prefer an explicit loop so we can assert no orphaned tasks.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        before = {t for t in asyncio.all_tasks(loop) if not t.done()}
        shutdown_pipeline(pipe)
        gc.collect()
        after = {t for t in asyncio.all_tasks(loop) if not t.done()}
        assert after - before == set()
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    # R3: file SQLite uses NullPool (no checkedout()). Dispose releases
    # connections; QueuePool backends still expose checkedout() == 0.
    persistence.dispose()
    pool = persistence.engine.pool
    if hasattr(pool, "checkedout"):
        assert pool.checkedout() == 0


def test_modules_stop_cleanly_without_open_positions():
    exchange = ScriptedFillExchange()
    pipe = wire_pipeline(exchange, make_config())
    shutdown_pipeline(pipe)
    assert not pipe.risk.is_running()
    assert not pipe.scanner.is_initialized()
    assert pipe.positions.open_count() == 0


def test_paper_adapter_lifecycle_never_hits_live_order_endpoints(monkeypatch):
    """PAPER mode: BUY → trailing → partial TP → SELL on PaperExchangeAdapter."""
    from app.core.exchange.adapter import PaperExchangeAdapter
    from app.core.exchange.manager import ExchangeManager
    from app.core.exchange.registry import ExchangeRegistry
    from app.core.services.order_validator import OrderValidator

    monkeypatch.setenv("TRADE_MODE", "PAPER")

    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=EXCHANGE,
        initial_quote=50_000.0,
        fee_rate=0.0,
        slippage_bps=0,
    )
    paper.connect()
    paper.set_mark_price(SYMBOL, 100.0)

    registry = ExchangeRegistry()
    registry.register(EXCHANGE, paper)
    manager = ExchangeManager(registry)

    config = make_config(
        trailing_activation=2.0,
        trailing_percent=2.5,
        partial_tp_activation=5.0,
        partial_tp_sell=50.0,
        stop_loss_percent=10.0,
    )
    pipe = wire_pipeline(manager, config)
    pipe.journal.set_trading_mode("PAPER")
    pipe.telegram.set_trading_mode("PAPER")
    pipe.risk.set_order_validator(OrderValidator(manager))

    seed_via_scanner_and_path_b(pipe, entry_price=106.0)
    position = pipe.positions.get(SYMBOL, exchange=EXCHANGE)
    assert position is not None
    entry = position.entry_price
    assert pipe.journal.get_open(SYMBOL, exchange=EXCHANGE).trading_mode == "PAPER"
    assert any(m.startswith("[PAPER]") for m in pipe.telegram_client.messages)

    trail_tick = entry * 1.03
    paper.set_mark_price(SYMBOL, trail_tick)
    pipe.risk.on_price_tick(make_ticker(trail_tick))
    assert position.stop_stage == "TRAILING"

    partial_tick = entry * 1.10
    paper.set_mark_price(SYMBOL, partial_tick)
    pipe.risk.on_price_tick(make_ticker(partial_tick))
    assert position.partial_exits_taken == 1

    crash = position.stop_price * 0.99
    paper.set_mark_price(SYMBOL, crash)
    pipe.risk.on_price_tick(make_ticker(crash))
    assert not pipe.positions.is_open(SYMBOL, exchange=EXCHANGE)
    shutdown_pipeline(pipe)
