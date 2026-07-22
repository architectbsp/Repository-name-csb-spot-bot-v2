"""
Sprint 12 -- Live Dashboard: DashboardService assembles a read-only
snapshot from PositionManager / WatchList / TradeJournal / RiskManager /
ticker cache. Pure aggregation -- no orders, no mutations.
"""

from datetime import UTC, datetime, timedelta

from app.core.config.settings import AppSettings
from app.core.domain.dashboard import DashboardSnapshot
from app.core.domain.position import Position, PositionState
from app.core.domain.trade_journal import (
    STATUS_CLOSED,
    STATUS_OPEN,
    TradeJournalEntry,
)
from app.core.exchange.models import ConnectionStatus, ExchangeState, ExchangeType
from app.core.market_data.models import NormalizedTicker
from app.core.services.dashboard_service import DashboardService
from app.core.watch_list import WatchList


class DummyExchange:
    def __init__(self, status=ConnectionStatus.CONNECTED):
        self.state = ExchangeState(
            exchange=ExchangeType.BINANCE,
            enabled=True,
            status=status,
        )


class DummyExchangeManager:
    def __init__(self, balance=1000.0, status=ConnectionStatus.CONNECTED):
        self._balance = balance
        self._exchange = DummyExchange(status)

    def active_exchange_type(self):
        return ExchangeType.BINANCE

    def enabled_exchange_types(self):
        return [ExchangeType.BINANCE]

    def enabled(self):
        return [self._exchange]

    def get_quote_balance(self, exchange_type, quote="USDT"):
        return self._balance


class DummyPositionManager:
    def __init__(self, positions=None):
        self._positions = positions or []

    def get_open_positions(self):
        return list(self._positions)


class DummyTradeJournal:
    def __init__(self, entries=None):
        self._entries = entries or []

    def list_all(self):
        return list(self._entries)


class DummyRiskManager:
    def __init__(self, realized=0.0, day_start=1000.0):
        self._realized = realized
        self._day_start = day_start

    def realized_pnl_today(self):
        return self._realized

    def day_start_balance(self):
        return self._day_start


class DummyMarketScanner:
    def __init__(self, tickers=None):
        self._tickers = tickers or []

    def last_scan_result(self):
        return list(self._tickers)


def make_service(**overrides) -> DashboardService:
    service = DashboardService()
    service.set_exchange_manager(
        overrides.get("exchange_manager", DummyExchangeManager())
    )
    service.set_position_manager(
        overrides.get("position_manager", DummyPositionManager())
    )
    service.set_watch_list(overrides.get("watch_list", WatchList()))
    service.set_trade_journal(
        overrides.get("trade_journal", DummyTradeJournal())
    )
    service.set_risk_manager(
        overrides.get("risk_manager", DummyRiskManager())
    )
    service.set_market_scanner(
        overrides.get("market_scanner", DummyMarketScanner())
    )
    service.set_config(overrides.get("config", AppSettings()))
    service.set_bot_running_fn(overrides.get("bot_running_fn", lambda: True))
    return service


def test_build_snapshot_reports_account_and_daily_pnl():
    service = make_service(
        risk_manager=DummyRiskManager(realized=25.0, day_start=1000.0),
        exchange_manager=DummyExchangeManager(balance=1250.5),
    )

    snap = service.build_snapshot()

    assert isinstance(snap, DashboardSnapshot)
    assert snap.bot_running is True
    assert snap.exchange_name == "BINANCE"
    assert snap.api_connected is True
    assert snap.quote_balance == 1250.5
    assert snap.daily_realized_pnl == 25.0
    assert snap.daily_pnl_percent == 2.5
    assert snap.day_start_balance == 1000.0


def test_build_snapshot_lists_open_positions_with_unrealized_pnl():
    position = Position(
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        stop_stage="TRAILING",
        state=PositionState.OPEN,
    )
    service = make_service(
        position_manager=DummyPositionManager([position]),
    )
    service.on_ticker_updated(
        NormalizedTicker(
            exchange=ExchangeType.BINANCE,
            symbol="BTC/USDT",
            last_price=110.0,
            volume_24h=1_000_000,
            change_24h=5.0,
            timestamp=1,
            raw_last_price="110.00000000",
        )
    )

    snap = service.build_snapshot()

    assert snap.open_position_count == 1
    row = snap.open_positions[0]
    assert row.symbol == "BTC/USDT"
    assert row.current_price == 110.0
    assert row.pnl_percent == 10.0
    assert row.stop_stage == "TRAILING"


def test_build_snapshot_lists_active_watch_and_cooldown_rows():
    wl = WatchList()
    wl.add("ETH/USDT")
    wl.begin_rising_watch("ETH/USDT", 2000.0)

    wl.add("SOL/USDT")
    wl.begin_falling_watch("SOL/USDT", 100.0)
    wl.begin_rising_watch("SOL/USDT", 101.0)
    wl.promote_to_buy_pending("SOL/USDT", 102.0)
    wl.promote_to_position_open("SOL/USDT", 102.0, 98.0)
    wl.close_position("SOL/USDT")
    until = datetime.now(UTC) + timedelta(hours=2)
    assert wl.enter_cooldown("SOL/USDT", until)

    service = make_service(watch_list=wl)
    snap = service.build_snapshot()

    assert snap.active_signal_count == 1
    assert snap.watch_list[0].symbol == "ETH/USDT"
    assert snap.watch_list[0].direction == "RISE"
    assert len(snap.cooldowns) == 1
    assert snap.cooldowns[0].symbol == "SOL/USDT"
    assert snap.cooldowns[0].remaining_seconds is not None
    assert snap.cooldowns[0].remaining_seconds > 0


def test_build_snapshot_report_24h_only_counts_recent_closed_trades():
    now = datetime.now(UTC)
    recent_win = TradeJournalEntry(
        symbol="AAA/USDT",
        entry_time=now - timedelta(hours=2),
        entry_price=10.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status=STATUS_CLOSED,
        exit_time=now - timedelta(hours=1),
        exit_price=11.0,
        exit_reason="TRAILING_STOP",
        pnl=5.0,
        pnl_percent=10.0,
    )
    recent_loss = TradeJournalEntry(
        symbol="BBB/USDT",
        entry_time=now - timedelta(hours=3),
        entry_price=10.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
        status=STATUS_CLOSED,
        exit_time=now - timedelta(minutes=30),
        exit_price=9.0,
        exit_reason="STOP_LOSS",
        pnl=-2.0,
        pnl_percent=-10.0,
    )
    old = TradeJournalEntry(
        symbol="CCC/USDT",
        entry_time=now - timedelta(days=3),
        entry_price=10.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status=STATUS_CLOSED,
        exit_time=now - timedelta(days=2),
        exit_price=12.0,
        exit_reason="TRAILING_STOP",
        pnl=20.0,
        pnl_percent=20.0,
    )
    still_open = TradeJournalEntry(
        symbol="DDD/USDT",
        entry_time=now,
        entry_price=10.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status=STATUS_OPEN,
    )

    service = make_service(
        trade_journal=DummyTradeJournal(
            [recent_win, recent_loss, old, still_open]
        )
    )
    snap = service.build_snapshot()

    assert snap.report_24h.total_trades == 2
    assert snap.report_24h.winning_trades == 1
    assert snap.report_24h.losing_trades == 1
    assert snap.report_24h.net_pnl == 3.0
    assert snap.report_24h.gross_profit == 5.0
    assert snap.report_24h.gross_loss == 2.0

    # History includes the older closed trade too (panel is not 24h-limited).
    symbols = {row.symbol for row in snap.trade_history}
    assert "AAA/USDT" in symbols
    assert "CCC/USDT" in symbols
    assert "DDD/USDT" not in symbols


def test_on_ticker_updated_seeds_coin_table_price_from_raw_string():
    wl = WatchList()
    wl.add("DOGE/USDT")
    wl.begin_falling_watch("DOGE/USDT", 0.1)

    service = make_service(watch_list=wl)
    service.on_ticker_updated(
        NormalizedTicker(
            exchange=ExchangeType.BINANCE,
            symbol="DOGE/USDT",
            last_price=0.1523,
            volume_24h=289_000_000,
            change_24h=1.02,
            timestamp=1,
            raw_last_price="0.15230000",
        )
    )

    snap = service.build_snapshot()

    assert len(snap.coins) == 1
    assert snap.coins[0].price_display == "0.15230000"
    assert snap.coins[0].signal == "WAIT"
    assert snap.coins[0].status == "WATCH_FALLING"


def test_build_snapshot_handles_missing_dependencies_gracefully():
    service = DashboardService()
    snap = service.build_snapshot()

    assert snap.coins == []
    assert snap.open_positions == []
    assert snap.quote_balance is None
    assert snap.bot_running is False
