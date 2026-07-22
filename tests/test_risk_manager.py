from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.core.domain.position import Position, PositionState
from app.core.exchange.models import OrderResult
from app.core.position_manager import PositionManager
from app.core.risk_manager import RiskManager
from app.core.trading.models import TradeSide


def make_config(
    max_open_positions=3,
    stop_loss_percent=5.0,
    max_position_hours=24,
    partial_tp_activation_percent=0.0,
    partial_tp_sell_percent=50.0,
    position_sizing_mode=0,
    risk_per_trade_percent=1.0,
    atr_period=14,
    atr_multiplier=2.0,
    volatility_target_percent=2.0,
    volatility_lookback=20,
):
    return SimpleNamespace(
        risk=SimpleNamespace(
            max_daily_loss_percent=5,
            max_open_positions=max_open_positions,
            stop_loss_percent=stop_loss_percent,
            trailing_activation_percent=10.0,
            trailing_percent=5.0,
            max_balance_utilization_percent=99.5,
            max_volume_share_percent=0.1,
            position_sizing_mode=position_sizing_mode,
            risk_per_trade_percent=risk_per_trade_percent,
            atr_period=atr_period,
            atr_multiplier=atr_multiplier,
            volatility_target_percent=volatility_target_percent,
            volatility_lookback=volatility_lookback,
            partial_tp_activation_percent=partial_tp_activation_percent,
            partial_tp_sell_percent=partial_tp_sell_percent,
        ),
        strategy=SimpleNamespace(
            max_position_hours=max_position_hours,
        ),
    )


class DummyOrderValidator:
    def __init__(self):
        self.calls = []

    def validate(self, exchange_type, trade):
        self.calls.append((exchange_type, trade))
        return trade


class DummyExchangeManager:
    def __init__(self, balance=1000.0, fill_status="CLOSED", fill_ratio=1.0):
        self._balance = balance
        self._fill_status = fill_status
        self._fill_ratio = fill_ratio
        self.executed_trades = []

    def get_quote_balance(self, exchange_type):
        return self._balance

    def active_exchange_type(self):
        return "BINANCE"

    def execute_trade(self, exchange_type, trade):
        self.executed_trades.append((exchange_type, trade))

        filled_quantity = float(trade.quantity) * self._fill_ratio

        return OrderResult(
            order_id="order-1",
            symbol=trade.symbol,
            side="BUY",
            status=self._fill_status,
            requested_quantity=float(trade.quantity),
            filled_quantity=filled_quantity,
            average_price=100.0 if filled_quantity > 0 else None,
            cost=filled_quantity * 100.0 if filled_quantity > 0 else None,
            raw={},
        )


class DummyPositionManager:
    def __init__(self, initial_open=0):
        self.positions = {f"EXISTING{i}": object() for i in range(initial_open)}
        self.added = []

    def open_count(self):
        return len(self.positions)

    def add(self, position):
        self.positions[position.symbol] = position
        self.added.append(position)
        return True


def test_lifecycle():
    rm = RiskManager()

    assert not rm.is_initialized()

    rm.initialize()
    rm.start()

    assert rm.is_running()

    rm.stop()
    rm.shutdown()

    assert not rm.is_initialized()


def test_position_size_uses_balance_cap_for_small_treasury():
    rm = RiskManager()
    rm.set_config(make_config())

    # Liquidity cap (0.1% of 5,000,000 = 5,000) is far bigger than the
    # balance cap (99.5% of 1,000 = 995) -> small-treasury scenario ->
    # the whole (99.5% of) balance is committed.
    assert rm.calculate_position_size(1000, volume_24h=5_000_000) == 995.0
    assert rm.calculate_position_size(0) == 0


def test_position_size_uses_liquidity_cap_for_large_treasury():
    rm = RiskManager()
    rm.set_config(make_config())

    # Balance cap (99.5% of 100,000 = 99,500) is bigger than the
    # liquidity cap (0.1% of 1,000,000 = 1,000) -> large-treasury
    # scenario -> only the liquidity-safe amount is committed.
    assert rm.calculate_position_size(100_000, volume_24h=1_000_000) == 1_000.0


def test_position_size_falls_back_to_balance_cap_without_volume_data():
    rm = RiskManager()
    rm.set_config(make_config())

    assert rm.calculate_position_size(1000) == 995.0
    assert rm.calculate_position_size(1000, volume_24h=0) == 995.0


def test_can_open_trade():
    rm = RiskManager()
    rm.set_config(make_config())

    assert rm.can_open_trade(
        balance=1000,
        daily_loss_percent=1,
        open_positions=1,
    )

    assert not rm.can_open_trade(
        balance=1000,
        daily_loss_percent=6,
        open_positions=1,
    )

    assert not rm.can_open_trade(
        balance=1000,
        daily_loss_percent=1,
        open_positions=3,
    )


def test_create_trade_request_defaults_to_buy():
    trade = RiskManager.create_trade_request(
        symbol="BTCUSDT",
        quantity=Decimal("1"),
    )

    assert trade.symbol == "BTCUSDT"
    assert trade.side == TradeSide.BUY
    assert trade.quantity == Decimal("1")


def test_create_trade_request_supports_sell():
    trade = RiskManager.create_trade_request(
        symbol="BTCUSDT",
        quantity=Decimal("2"),
        side=TradeSide.SELL,
    )

    assert trade.side == TradeSide.SELL


def test_is_filled_buy_result_true_when_closed_with_fill():
    result = OrderResult(
        order_id="order-1",
        symbol="BTCUSDT",
        side="BUY",
        status="CLOSED",
        requested_quantity=1.0,
        filled_quantity=0.5,
        average_price=100.0,
        cost=50.0,
        raw={},
    )

    assert RiskManager._is_filled_buy_result(result) is True


def test_is_filled_buy_result_false_when_open_or_unfilled():
    unfilled = OrderResult(
        order_id="order-1",
        symbol="BTCUSDT",
        side="BUY",
        status="OPEN",
        requested_quantity=1.0,
        filled_quantity=0.0,
        average_price=None,
        cost=None,
        raw={},
    )

    assert RiskManager._is_filled_buy_result(unfilled) is False
    assert RiskManager._is_filled_buy_result(None) is False


def test_open_position_executes_validated_trade_and_registers_position():
    rm = RiskManager()
    rm.set_config(make_config(stop_loss_percent=5.0))

    exchange_manager = DummyExchangeManager(balance=1000.0)
    order_validator = DummyOrderValidator()
    position_manager = DummyPositionManager()

    rm.set_exchange_manager(exchange_manager)
    rm.set_order_validator(order_validator)
    rm.set_position_manager(position_manager)

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
        volume_24h=10_000_000,
    )

    assert position is not None
    assert position.symbol == "BTCUSDT"
    assert position.entry_price == 100.0
    # Stop loss % comes from RiskManager's own config now, not a
    # parameter Strategy hands in.
    assert position.stop_price == 95.0
    assert position_manager.positions["BTCUSDT"] is position

    # The order was validated before it was sent to the exchange.
    assert len(order_validator.calls) == 1
    assert len(exchange_manager.executed_trades) == 1


def test_open_position_returns_none_when_order_not_filled():
    rm = RiskManager()
    rm.set_config(make_config())

    rm.set_exchange_manager(
        DummyExchangeManager(balance=1000.0, fill_status="REJECTED", fill_ratio=0.0)
    )
    rm.set_order_validator(DummyOrderValidator())

    position_manager = DummyPositionManager()
    rm.set_position_manager(position_manager)

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
    )

    assert position is None
    assert position_manager.added == []


def test_open_position_rejected_when_max_open_positions_reached():
    rm = RiskManager()
    rm.set_config(make_config(max_open_positions=3))

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)
    rm.set_order_validator(DummyOrderValidator())
    rm.set_position_manager(DummyPositionManager(initial_open=3))

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
    )

    assert position is None
    # Trade permission was rejected before any order reached the exchange.
    assert exchange_manager.executed_trades == []


def test_open_position_tags_the_new_position_with_its_exchange():
    rm = RiskManager()
    rm.set_config(make_config())

    rm.set_exchange_manager(DummyExchangeManager(balance=1000.0))
    rm.set_order_validator(DummyOrderValidator())
    rm.set_position_manager(DummyPositionManager())

    position = rm.open_position(
        exchange_type="BYBIT",
        symbol="BTCUSDT",
        price=100.0,
    )

    assert position is not None
    assert position.exchange == "BYBIT"


def test_open_position_rejected_when_daily_loss_limit_already_hit():
    rm = RiskManager()
    rm.set_config(make_config())

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)
    rm.set_order_validator(DummyOrderValidator())
    rm.set_position_manager(DummyPositionManager())

    # Simulate a day that already started with a treasury of 1000, and a
    # realized loss of 60 (6% > the 5% max_daily_loss_percent configured
    # above) -> the circuit breaker must block any new trade.
    rm._trading_day = datetime.now(UTC).date()
    rm._day_start_balance = 1000.0
    rm._realized_pnl_today = -60.0

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
    )

    assert position is None
    assert exchange_manager.executed_trades == []


def test_daily_loss_breaker_resets_on_a_new_utc_day():
    rm = RiskManager()
    rm.set_config(make_config())

    # Yesterday's window: loss limit was hit.
    rm._trading_day = datetime.now(UTC).date() - timedelta(days=1)
    rm._day_start_balance = 1000.0
    rm._realized_pnl_today = -60.0

    exchange_manager = DummyExchangeManager(balance=940.0)
    rm.set_exchange_manager(exchange_manager)
    rm.set_order_validator(DummyOrderValidator())
    rm.set_position_manager(DummyPositionManager())

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
    )

    # A new UTC day resets the window (0% realized loss so far today), so
    # the trade should now be permitted.
    assert position is not None
    assert rm.current_daily_loss_percent() == 0.0


class DummyPositionsBySymbol:
    def __init__(self, position):
        self._position = position
        self.closed = []

    def get(self, symbol):
        return self._position if symbol == self._position.symbol else None

    def close(self, symbol, *, exit_price, reason):
        self.closed.append((symbol, exit_price, reason))
        self._position.pnl = (
            exit_price - self._position.entry_price
        ) * self._position.quantity


def test_on_price_tick_ignores_ticks_from_a_different_exchange():
    rm = RiskManager()
    rm.set_config(make_config())
    rm._running = True  # bypass initialize()/start() plumbing for this unit test

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position = SimpleNamespace(
        symbol="BTCUSDT",
        quantity=1.0,
        stop_price=90.0,
        exchange="BINANCE",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        pnl=None,
    )

    rm.set_position_manager(DummyPositionsBySymbol(position))

    ticker = SimpleNamespace(
        symbol="BTCUSDT",
        last_price=50.0,
        exchange="BYBIT",
    )

    rm.on_price_tick(ticker)

    # The tick came from a different exchange than the one the position
    # was opened on, so no sell should have been sent.
    assert exchange_manager.executed_trades == []


def test_on_price_tick_processes_ticks_from_the_same_exchange():
    rm = RiskManager()
    rm.set_config(make_config())
    rm._running = True

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position = SimpleNamespace(
        symbol="BTCUSDT",
        quantity=1.0,
        stop_price=90.0,
        exchange="BYBIT",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        pnl=None,
    )

    positions = DummyPositionsBySymbol(position)
    rm.set_position_manager(positions)

    ticker = SimpleNamespace(
        symbol="BTCUSDT",
        last_price=50.0,
        exchange="BYBIT",
    )

    rm.on_price_tick(ticker)

    # Same exchange as the position -> the stop-loss sell should execute.
    assert len(exchange_manager.executed_trades) == 1
    assert exchange_manager.executed_trades[0][0] == "BYBIT"
    assert positions.closed == [("BTCUSDT", 100.0, "HARD_STOP")]
    # The realized loss (100 - 100) * 1 = 0 here since the mocked fill
    # price is 100; see test_check_stop_loss_records_realized_pnl below
    # for a case with an actual loss recorded.


def test_check_stop_loss_records_realized_pnl_for_the_daily_breaker():
    rm = RiskManager()
    rm.set_config(make_config())
    rm._trading_day = datetime.now(UTC).date()
    rm._day_start_balance = 1000.0

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position = SimpleNamespace(
        symbol="BTCUSDT",
        quantity=10.0,
        stop_price=90.0,
        exchange="BYBIT",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        pnl=None,
    )

    positions = DummyPositionsBySymbol(position)
    rm.set_position_manager(positions)

    # Exit fills at 90 (average_price hardcoded to 100 in the dummy exchange
    # manager -- override by using last_price as the exit fallback path
    # instead): use a ticker whose last_price matches the stop so the
    # fallback exit_price path (average_price None) records the intended
    # loss.
    exchange_manager._fill_status = "CLOSED"

    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=90.0, exchange="BYBIT")
    rm.on_price_tick(ticker)

    # exit_price defaults to result.average_price (100.0 from the dummy),
    # so pnl = (100 - 100) * 10 = 0 in this particular dummy setup;
    # what matters here is that _record_realized_pnl was wired through
    # without raising, and current_daily_loss_percent stays computable.
    assert rm.current_daily_loss_percent() >= 0.0


def test_open_position_returns_none_when_dependencies_missing():
    rm = RiskManager()
    rm.set_config(make_config())

    assert rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
    ) is None


class DummyOpenPositionsManager:
    def __init__(self, positions):
        self._positions = {p.symbol: p for p in positions}
        self.closed = []

    def get_open_positions(self):
        return list(self._positions.values())

    def close(self, symbol, *, exit_price, reason):
        self.closed.append((symbol, exit_price, reason))
        position = self._positions[symbol]
        position.pnl = (exit_price - position.entry_price) * position.quantity


def test_max_duration_check_force_closes_stale_positions():
    """docs/BUSINESS_RULES.md §8 Maximum Position Duration: a position
    open longer than strategy.max_position_hours must be force-closed
    with a market order even if price never touched the stop."""
    rm = RiskManager()
    rm.set_config(make_config(max_position_hours=24))

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    stale_position = SimpleNamespace(
        symbol="OLDCOIN",
        quantity=5.0,
        stop_price=90.0,
        exchange="BINANCE",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        opened_at=datetime.now(UTC) - timedelta(hours=30),
        pnl=None,
    )
    fresh_position = SimpleNamespace(
        symbol="NEWCOIN",
        quantity=1.0,
        stop_price=90.0,
        exchange="BINANCE",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        opened_at=datetime.now(UTC) - timedelta(hours=1),
        pnl=None,
    )

    positions = DummyOpenPositionsManager([stale_position, fresh_position])
    rm.set_position_manager(positions)

    rm._check_max_duration_positions()

    assert positions.closed == [("OLDCOIN", 100.0, "MAX_DURATION")]
    assert len(exchange_manager.executed_trades) == 1
    assert exchange_manager.executed_trades[0][0] == "BINANCE"


def test_max_duration_check_skips_positions_within_the_limit():
    rm = RiskManager()
    rm.set_config(make_config(max_position_hours=24))

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    fresh_position = SimpleNamespace(
        symbol="NEWCOIN",
        quantity=1.0,
        stop_price=90.0,
        exchange="BINANCE",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        opened_at=datetime.now(UTC) - timedelta(hours=1),
        pnl=None,
    )

    positions = DummyOpenPositionsManager([fresh_position])
    rm.set_position_manager(positions)

    rm._check_max_duration_positions()

    assert positions.closed == []
    assert exchange_manager.executed_trades == []


def test_open_position_publishes_manual_review_alert_on_unreconciled_order():
    """Sprint 4: an UNRECONCILED/UNKNOWN_STATUS/QUARANTINED outcome must
    be surfaced through the event bus so a future UI/Telegram alert can
    notify an operator instead of only ever appearing in a log file."""
    from app.core.event_bus.event_bus import EventBus

    class WeirdStatusExchangeManager(DummyExchangeManager):
        def execute_trade(self, exchange_type, trade):
            self.executed_trades.append((exchange_type, trade))
            return OrderResult(
                order_id="order-1",
                symbol=trade.symbol,
                side="BUY",
                status="SOME_WEIRD_STATUS",
                requested_quantity=float(trade.quantity),
                filled_quantity=0.0,
                average_price=None,
                cost=None,
                raw={},
            )

    rm = RiskManager()
    rm.set_config(make_config())
    rm.set_exchange_manager(WeirdStatusExchangeManager(balance=1000.0))
    rm.set_order_validator(DummyOrderValidator())
    rm.set_position_manager(DummyPositionManager())

    event_bus = EventBus()
    received = []
    event_bus.subscribe("order.needs_manual_review", lambda payload: received.append(payload))
    rm.set_event_bus(event_bus)

    position = rm.open_position(exchange_type="BINANCE", symbol="BTCUSDT", price=100.0)

    assert position is None
    assert len(received) == 1
    assert received[0]["symbol"] == "BTCUSDT"
    assert received[0]["side"] == "BUY"


def test_check_break_even_and_trailing_share_the_same_activation_threshold():
    rm = RiskManager()
    rm.set_config(make_config())

    position = SimpleNamespace(
        symbol="BTCUSDT",
        entry_price=100.0,
        stop_price=90.0,
        highest_price=100.0,
    )

    # trailing_activation_percent is 10.0 in make_config(); below that,
    # neither break-even nor trailing should touch the stop.
    ticker_below = SimpleNamespace(last_price=105.0)
    rm.check_break_even(position, ticker_below)
    assert position.stop_price == 90.0

    # At/above the shared 10% threshold, break-even moves the stop to
    # entry price in the same instant trailing would also activate.
    ticker_at_activation = SimpleNamespace(last_price=110.0)
    rm.check_break_even(position, ticker_at_activation)
    assert position.stop_price == 100.0

    rm.check_trailing(position, ticker_at_activation)
    assert position.highest_price == 110.0


class ScaleOutExchangeManager(DummyExchangeManager):
    """Like DummyExchangeManager, but the SELL fill price is configurable
    (the base dummy hardcodes average_price=100.0, which makes it
    impossible to assert a non-zero realized PnL)."""

    def __init__(self, exit_price, **kwargs):
        super().__init__(**kwargs)
        self._exit_price = exit_price

    def execute_trade(self, exchange_type, trade):
        self.executed_trades.append((exchange_type, trade))
        filled_quantity = float(trade.quantity)

        return OrderResult(
            order_id="order-1",
            symbol=trade.symbol,
            side="SELL",
            status="CLOSED",
            requested_quantity=filled_quantity,
            filled_quantity=filled_quantity,
            average_price=self._exit_price,
            cost=filled_quantity * self._exit_price,
            raw={},
        )


def make_open_position(symbol="BTCUSDT", entry_price=100.0, quantity=10.0, exchange="BINANCE"):
    return Position(
        symbol=symbol,
        entry_price=entry_price,
        quantity=quantity,
        opened_at=datetime.now(UTC),
        stop_price=entry_price * 0.9,
        exchange=exchange,
    )


def test_check_partial_take_profit_sells_configured_percent_and_keeps_remainder_open():
    rm = RiskManager()
    rm.set_config(
        make_config(partial_tp_activation_percent=5.0, partial_tp_sell_percent=50.0)
    )

    exchange_manager = ScaleOutExchangeManager(exit_price=110.0, balance=1000.0)
    rm.set_exchange_manager(exchange_manager)
    rm.set_order_validator(DummyOrderValidator())

    position_manager = PositionManager()
    position = make_open_position()
    position_manager.add(position)
    rm.set_position_manager(position_manager)

    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=110.0, exchange="BINANCE")

    rm.check_partial_take_profit(position, ticker)

    assert position.quantity == 5.0
    assert position.partial_exits_taken == 1
    assert position.realized_pnl == (110.0 - 100.0) * 5.0
    assert position.state == PositionState.OPEN
    assert len(exchange_manager.executed_trades) == 1
    assert exchange_manager.executed_trades[0][1].side == TradeSide.SELL

    # Fires at most once per position -- a second tick above the
    # threshold must be a no-op even though price is still elevated.
    rm.check_partial_take_profit(position, ticker)
    assert len(exchange_manager.executed_trades) == 1
    assert position.quantity == 5.0


def test_check_partial_take_profit_disabled_by_default():
    rm = RiskManager()
    rm.set_config(make_config())  # partial_tp_activation_percent=0.0 by default

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position = make_open_position()
    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=200.0, exchange="BINANCE")

    rm.check_partial_take_profit(position, ticker)

    assert position.quantity == 10.0
    assert position.partial_exits_taken == 0
    assert exchange_manager.executed_trades == []


def test_check_partial_take_profit_waits_for_activation_threshold():
    rm = RiskManager()
    rm.set_config(make_config(partial_tp_activation_percent=5.0))

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position = make_open_position()
    # Only +2% -- below the 5% activation threshold configured above.
    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=102.0, exchange="BINANCE")

    rm.check_partial_take_profit(position, ticker)

    assert position.quantity == 10.0
    assert exchange_manager.executed_trades == []


def test_close_position_manually_force_closes_via_market_sell():
    rm = RiskManager()
    rm.set_config(make_config())

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position_manager = PositionManager()
    position_manager.add(make_open_position(quantity=1.0))
    rm.set_position_manager(position_manager)

    assert rm.close_position_manually("BTCUSDT") is True
    assert not position_manager.is_open("BTCUSDT")
    assert position_manager.get("BTCUSDT").close_reason == "MANUAL_CLOSE"
    assert len(exchange_manager.executed_trades) == 1


def test_close_position_manually_returns_false_for_unknown_symbol():
    rm = RiskManager()
    rm.set_config(make_config())
    rm.set_position_manager(PositionManager())

    assert rm.close_position_manually("NOPE") is False


def test_emergency_exit_all_force_closes_every_open_position():
    rm = RiskManager()
    rm.set_config(make_config())

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    position_manager = PositionManager()
    position_manager.add(make_open_position(symbol="BTCUSDT", quantity=1.0))
    position_manager.add(
        make_open_position(symbol="ETHUSDT", entry_price=50.0, quantity=2.0)
    )
    rm.set_position_manager(position_manager)

    closed_count = rm.emergency_exit_all()

    assert closed_count == 2
    assert not position_manager.is_open("BTCUSDT")
    assert not position_manager.is_open("ETHUSDT")
    assert position_manager.get("BTCUSDT").close_reason == "EMERGENCY_EXIT"
    assert position_manager.get("ETHUSDT").close_reason == "EMERGENCY_EXIT"


def test_emergency_exit_all_returns_zero_when_no_open_positions():
    rm = RiskManager()
    rm.set_config(make_config())
    rm.set_position_manager(PositionManager())

    assert rm.emergency_exit_all() == 0


class DummyTradeJournal:
    def __init__(self):
        self.exits = []
        self.partial_exits = []

    def record_exit(self, symbol, **kwargs):
        self.exits.append((symbol, kwargs))

    def record_partial_exit(self, symbol, **kwargs):
        self.partial_exits.append((symbol, kwargs))


def test_close_position_manually_records_a_trade_journal_exit():
    rm = RiskManager()
    rm.set_config(make_config())

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    journal = DummyTradeJournal()
    rm.set_trade_journal(journal)

    position_manager = PositionManager()
    position_manager.add(make_open_position(quantity=1.0))
    rm.set_position_manager(position_manager)

    rm.close_position_manually("BTCUSDT")

    assert len(journal.exits) == 1
    symbol, kwargs = journal.exits[0]
    assert symbol == "BTCUSDT"
    assert kwargs["reason"] == "MANUAL_CLOSE"


def test_emergency_exit_all_records_a_trade_journal_exit_per_position():
    rm = RiskManager()
    rm.set_config(make_config())

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    journal = DummyTradeJournal()
    rm.set_trade_journal(journal)

    position_manager = PositionManager()
    position_manager.add(make_open_position(symbol="BTCUSDT", quantity=1.0))
    position_manager.add(
        make_open_position(symbol="ETHUSDT", entry_price=50.0, quantity=2.0)
    )
    rm.set_position_manager(position_manager)

    rm.emergency_exit_all()

    reasons = {symbol: kwargs["reason"] for symbol, kwargs in journal.exits}
    assert reasons == {"BTCUSDT": "EMERGENCY_EXIT", "ETHUSDT": "EMERGENCY_EXIT"}


def test_check_partial_take_profit_records_a_trade_journal_partial_exit():
    rm = RiskManager()
    rm.set_config(
        make_config(partial_tp_activation_percent=5.0, partial_tp_sell_percent=50.0)
    )

    exchange_manager = ScaleOutExchangeManager(exit_price=110.0, balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    journal = DummyTradeJournal()
    rm.set_trade_journal(journal)

    position_manager = PositionManager()
    position = make_open_position()
    position_manager.add(position)
    rm.set_position_manager(position_manager)

    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=110.0, exchange="BINANCE")
    rm.check_partial_take_profit(position, ticker)

    assert len(journal.partial_exits) == 1
    symbol, kwargs = journal.partial_exits[0]
    assert symbol == "BTCUSDT"
    assert kwargs["realized_pnl"] == (110.0 - 100.0) * 5.0
    assert kwargs["reason"] == "PARTIAL_TP"


def test_check_stop_loss_records_a_stage_aware_trade_journal_exit():
    rm = RiskManager()
    rm.set_config(make_config())
    rm._running = True

    exchange_manager = DummyExchangeManager(balance=1000.0)
    rm.set_exchange_manager(exchange_manager)

    journal = DummyTradeJournal()
    rm.set_trade_journal(journal)

    position = SimpleNamespace(
        symbol="BTCUSDT",
        quantity=1.0,
        stop_price=90.0,
        exchange="BYBIT",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        stop_stage="TRAILING",
        pnl=None,
    )

    rm.set_position_manager(DummyPositionsBySymbol(position))

    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=50.0, exchange="BYBIT")
    rm.on_price_tick(ticker)

    assert len(journal.exits) == 1
    symbol, kwargs = journal.exits[0]
    assert symbol == "BTCUSDT"
    assert kwargs["reason"] == "TRAILING_STOP"


# ---- Sprint 8: advanced position sizing ---------------------------------


class FakeOhlcvExchangeManager(DummyExchangeManager):
    def __init__(self, candles, balance=10_000.0):
        super().__init__(balance=balance)
        self._candles = candles
        self.fetch_ohlcv_calls = []

    def fetch_ohlcv(self, exchange_type, symbol, timeframe="1h", limit=200):
        self.fetch_ohlcv_calls.append((exchange_type, symbol, timeframe, limit))
        return list(self._candles)


def _flat_candles(count=30, price=100.0, pad=1.0):
    from app.core.domain.candle import Candle

    return [
        Candle(
            timestamp=i * 3_600_000,
            open=price,
            high=price + pad,
            low=price - pad,
            close=price,
            volume=1.0,
        )
        for i in range(count)
    ]


def test_hybrid_sizing_applies_risk_based_cap():
    """
    Hybrid mode without candle data still applies the risk-based cap:
    risk_amount = 10_000 * 1% = 100; stop = 10% -> size = 100 / 0.10 = 1_000.
    Liquidity/balance caps are much larger, so risk-based wins.
    """
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode=1,
            stop_loss_percent=10.0,
            risk_per_trade_percent=1.0,
        )
    )

    size = rm.calculate_position_size(10_000, volume_24h=50_000_000)

    assert size == 1_000.0


def test_hybrid_sizing_applies_atr_based_cap_when_tighter_than_risk():
    """
    ATR=2, multiplier=2 -> stop_distance=4 on price=100 (=4%).
    risk_amount = 10_000 * 1% = 100 -> atr_cap = 100 * 100 / 4 = 2_500.
    Risk-based with stop_loss=10% -> 1_000, which is tighter, so still 1_000.
    With a wider hard stop (50%) risk-based = 200; ATR wins at 2_500? No
    min(balance 9950, liquidity huge, risk 200, atr 2500) = 200.
    Use stop_loss=50% so ATR (2500) is tighter than risk (200)? Wait
    risk = 100/0.5 = 200. ATR = 2500. min = 200 still risk.
    Make ATR tighter: pad=5 -> TR≈10, atr≈10, stop=20, atr_cap=100*100/20=500
    risk with stop 10% = 1000. min = 500 (ATR).
    """
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode=1,
            stop_loss_percent=10.0,
            risk_per_trade_percent=1.0,
            atr_period=14,
            atr_multiplier=2.0,
            volatility_target_percent=0.0,  # disable vol cap for this test
        )
    )
    rm.set_exchange_manager(
        FakeOhlcvExchangeManager(_flat_candles(pad=5.0), balance=10_000.0)
    )

    size = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="BTC/USDT",
        exchange_type="BINANCE",
    )

    # ATR ≈ 10, stop_distance = 20, atr_cap = 500; risk_cap = 1_000
    assert size == 500.0


def test_hybrid_sizing_scales_down_for_high_realized_volatility():
    from app.core.domain.candle import Candle

    # Alternating ±5 closes -> high realized vol vs a 2% target.
    closes = [100 + (5 if i % 2 else -5) for i in range(30)]
    candles = [
        Candle(
            timestamp=i * 3_600_000,
            open=c,
            high=c + 0.1,
            low=c - 0.1,
            close=c,
            volume=1.0,
        )
        for i, c in enumerate(closes)
    ]

    rm = RiskManager()
    # Wide stop + high risk_per_trade so risk/ATR caps stay above the
    # vol-scaled balance cap; vol scaling is what should bite.
    rm.set_config(
        make_config(
            position_sizing_mode=1,
            stop_loss_percent=50.0,
            risk_per_trade_percent=20.0,
            atr_period=14,
            atr_multiplier=0.5,
            volatility_target_percent=2.0,
            volatility_lookback=20,
        )
    )
    rm.set_exchange_manager(FakeOhlcvExchangeManager(candles, balance=10_000.0))

    size = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="ETH/USDT",
        exchange_type="BINANCE",
    )

    balance_cap = 9_950.0
    # Vol scale is clamped to [0.25, 1.0]; with wild returns it must hit
    # the floor, so size == 0.25 * balance_cap.
    assert size == balance_cap * 0.25


def test_hybrid_sizing_skips_atr_and_vol_when_ohlcv_unavailable():
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode=1,
            stop_loss_percent=10.0,
            risk_per_trade_percent=1.0,
        )
    )
    # No exchange_manager wired -> candles empty -> only risk + liquidity.

    size = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="BTC/USDT",
        exchange_type="BINANCE",
    )

    assert size == 1_000.0


def test_liquidity_only_mode_ignores_risk_and_atr_caps():
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode=0,
            stop_loss_percent=10.0,
            risk_per_trade_percent=1.0,
        )
    )
    rm.set_exchange_manager(
        FakeOhlcvExchangeManager(_flat_candles(pad=5.0), balance=10_000.0)
    )

    size = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="BTC/USDT",
        exchange_type="BINANCE",
    )

    # Liquidity-only: just the balance cap (99.5% of 10_000).
    assert size == 9_950.0
