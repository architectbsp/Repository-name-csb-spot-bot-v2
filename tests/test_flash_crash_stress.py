"""
Flash-crash / slippage stress simulations.

Documents and locks in expected spot behavior:
- Stop / trailing triggers on the tick last price.
- The exit is a market sell, so the fill can slip *through* the stop
  (worse than the trigger). Realized PnL uses the fill, not the stop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.domain.position import CloseReason, Position, PositionState
from app.core.exchange.adapter import PaperExchangeAdapter
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType, OrderResult
from app.core.exchange.registry import ExchangeRegistry
from app.core.position_manager import PositionManager
from app.core.risk_manager import RiskManager
from app.core.services.order_execution import OrderExecutionService
from app.core.services.order_validator import OrderValidator
from app.core.trading.models import TradeSide


SYMBOL = "BTC/USDT"
EXCHANGE = ExchangeType.BINANCE


class _SlippageFillExchange:
    """
    Executes sells at ``mark_price * (1 - sell_slippage_percent/100)``.
    Callers update ``mark_price`` as ticks arrive (flash-crash path).
    """

    def __init__(self, *, mark_price: float, sell_slippage_percent: float) -> None:
        self.mark_price = float(mark_price)
        self.sell_slippage_percent = float(sell_slippage_percent)
        self.executed: list[tuple] = []

    def get_quote_balance(self, exchange_type):
        return 100_000.0

    def active_exchange_type(self):
        return EXCHANGE

    def execute_trade(self, exchange_type, trade):
        self.executed.append((exchange_type, trade))
        qty = float(trade.quantity)
        if trade.side == TradeSide.SELL:
            fill = self.mark_price * (1.0 - self.sell_slippage_percent / 100.0)
            side = "SELL"
        else:
            fill = self.mark_price
            side = "BUY"
        return OrderResult(
            order_id="stress-1",
            symbol=trade.symbol,
            side=side,
            status="CLOSED",
            requested_quantity=qty,
            filled_quantity=qty,
            average_price=fill,
            cost=qty * fill,
            raw={"stress": True, "mark": self.mark_price, "fill": fill},
        )


class _RecordingPositions:
    def __init__(self, position: Position) -> None:
        self._position = position
        self.closed: list[tuple] = []

    def get(self, symbol, exchange=None):
        if self._position.state != PositionState.OPEN:
            return None
        if symbol != self._position.symbol:
            return None
        return self._position

    def is_open(self, symbol, exchange=None):
        return self.get(symbol, exchange=exchange) is not None

    def open_count(self):
        return 1 if self._position.state == PositionState.OPEN else 0

    def close(self, symbol, *, exit_price, reason, exchange=None):
        self.closed.append((symbol, exit_price, reason))
        self._position.state = PositionState.CLOSED
        self._position.exit_price = exit_price
        self._position.pnl = (
            exit_price - self._position.entry_price
        ) * self._position.quantity
        self._position.pnl_percent = (
            (exit_price - self._position.entry_price) / self._position.entry_price
        ) * 100.0


def _config(*, stop_loss_percent=10.0, trailing_activation=2.0, trailing_percent=2.5):
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
            partial_tp_activation_percent=0.0,
            partial_tp_sell_percent=50.0,
            kelly_fraction=0.5,
            kelly_min_trades=10,
        ),
        strategy=SimpleNamespace(
            max_position_hours=24,
            trading_hours_enabled=0,
            weekend_closed=0,
            quiet_start_hour_utc=2,
            quiet_end_hour_utc=5,
        ),
    )


def _wire_rm(exchange, positions, config) -> RiskManager:
    rm = RiskManager()
    rm.set_config(config)
    rm.set_exchange_manager(exchange)
    rm.set_order_validator(SimpleNamespace(validate=lambda _e, trade: trade))
    rm.set_position_manager(positions)
    # Bypass lazy OrderExecutionService construction quirks: inject a
    # real one bound to the slippage exchange.
    rm._order_execution = OrderExecutionService(
        exchange,
        retry_policy=None,
        timeout=None,
        pending_poll_attempts=1,
    )
    rm.initialize()
    rm.start()
    return rm


def test_flash_crash_hard_stop_fills_worse_than_stop_due_to_slippage():
    """
    Entry 100, hard stop 90 (-10%). One tick dumps last to 90 (exactly
    -10%). Market sell slips another 2% → fill ~88.2. PnL must use the
    slipped fill, not the stop price.
    """
    entry = 100.0
    stop = 90.0
    crash_last = 90.0
    sell_slippage_percent = 2.0
    expected_fill = crash_last * (1.0 - sell_slippage_percent / 100.0)

    position = Position(
        symbol=SYMBOL,
        entry_price=entry,
        quantity=10.0,
        opened_at=datetime.now(UTC),
        stop_price=stop,
        exchange=EXCHANGE,
        state=PositionState.OPEN,
        stop_stage="HARD",
    )
    positions = _RecordingPositions(position)
    exchange = _SlippageFillExchange(
        mark_price=entry,
        sell_slippage_percent=sell_slippage_percent,
    )
    rm = _wire_rm(exchange, positions, _config(stop_loss_percent=10.0))

    # Single-tick flash crash to the hard stop.
    exchange.mark_price = crash_last
    ticker = SimpleNamespace(
        symbol=SYMBOL,
        last_price=crash_last,
        exchange=EXCHANGE,
        raw_last_price=f"{crash_last:.8f}",
    )
    rm.on_price_tick(ticker)

    assert len(positions.closed) == 1
    symbol, exit_price, reason = positions.closed[0]
    assert symbol == SYMBOL
    assert reason == CloseReason.STOP_LOSS or reason == "STOP_LOSS"
    assert exit_price == expected_fill
    assert exit_price < stop  # slipped through the stop
    # Theoretical stop PnL would be (90-100)*10 = -100; slipped is worse.
    assert position.pnl == (expected_fill - entry) * 10.0
    assert position.pnl < (stop - entry) * 10.0


def test_flash_crash_trailing_stop_also_respects_slippage_on_exit():
    """
    Price pumps to activate trailing, then dumps 10% in one tick through
    the trail. Exit fill includes adverse slippage below the trigger.
    """
    entry = 100.0
    peak = 110.0
    trailing_percent = 2.5
    trail_stop = peak * (1.0 - trailing_percent / 100.0)  # 107.25
    # One-tick dump ~10% from peak → 99.0, well through the trail.
    crash_last = peak * 0.90
    sell_slippage_percent = 1.5
    expected_fill = crash_last * (1.0 - sell_slippage_percent / 100.0)

    position = Position(
        symbol=SYMBOL,
        entry_price=entry,
        quantity=5.0,
        opened_at=datetime.now(UTC),
        stop_price=entry * 0.90,
        exchange=EXCHANGE,
        state=PositionState.OPEN,
        highest_price=entry,
        stop_stage="HARD",
    )
    positions = _RecordingPositions(position)
    exchange = _SlippageFillExchange(
        mark_price=entry,
        sell_slippage_percent=sell_slippage_percent,
    )
    rm = _wire_rm(
        exchange,
        positions,
        _config(
            stop_loss_percent=10.0,
            trailing_activation=2.0,
            trailing_percent=trailing_percent,
        ),
    )

    # Pump → activate / raise trailing stop.
    exchange.mark_price = peak
    rm.on_price_tick(
        SimpleNamespace(
            symbol=SYMBOL,
            last_price=peak,
            exchange=EXCHANGE,
            raw_last_price=f"{peak:.8f}",
        )
    )
    assert position.stop_stage == "TRAILING"
    assert abs(position.stop_price - trail_stop) < 1e-9
    assert position.state == PositionState.OPEN

    # Flash crash through the trail in one tick.
    exchange.mark_price = crash_last
    rm.on_price_tick(
        SimpleNamespace(
            symbol=SYMBOL,
            last_price=crash_last,
            exchange=EXCHANGE,
            raw_last_price=f"{crash_last:.8f}",
        )
    )

    assert len(positions.closed) == 1
    _, exit_price, reason = positions.closed[0]
    assert reason in {CloseReason.TRAILING_STOP, "TRAILING_STOP"}
    assert exit_price == expected_fill
    assert exit_price < crash_last
    assert exit_price < trail_stop


def test_paper_adapter_sell_slippage_bps_worsens_exit_fill():
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=EXCHANGE,
        initial_quote=10_000.0,
        fee_rate=0.0,
        slippage_bps=100,  # 1%
    )
    paper.connect()
    paper.set_mark_price(SYMBOL, 100.0)

    # Seed base inventory without slippage by temporarily disabling it.
    paper._slippage_bps = 0.0
    paper.place_market_buy(SYMBOL, 10.0)
    paper._slippage_bps = 100.0

    sell = paper.place_market_sell(SYMBOL, 10.0)
    assert sell.average_price == 99.0
    assert paper.fetch_quote_balance("USDT") == 10_000.0 - 1000.0 + 990.0


def test_paper_flash_crash_end_to_end_via_exchange_manager():
    """Integration: RiskManager + PaperExchangeAdapter with slippage."""
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=EXCHANGE,
        initial_quote=50_000.0,
        fee_rate=0.0,
        slippage_bps=200,  # 2%
    )
    paper.connect()
    paper.set_mark_price(SYMBOL, 100.0)
    # Flat buy to open inventory for the position we inject.
    paper._slippage_bps = 0.0
    buy = paper.place_market_buy(SYMBOL, 10.0)
    paper._slippage_bps = 200.0

    registry = ExchangeRegistry()
    registry.register(EXCHANGE, paper)
    manager = ExchangeManager(registry)

    position = Position(
        symbol=SYMBOL,
        entry_price=buy.average_price or 100.0,
        quantity=10.0,
        opened_at=datetime.now(UTC),
        stop_price=90.0,
        exchange=EXCHANGE,
        state=PositionState.OPEN,
        stop_stage="HARD",
    )
    pm = PositionManager()
    assert pm.add(position)

    rm = RiskManager()
    rm.set_config(_config(stop_loss_percent=10.0))
    rm.set_exchange_manager(manager)
    rm.set_order_validator(OrderValidator(manager))
    rm.set_position_manager(pm)
    rm._order_execution = OrderExecutionService(manager, pending_poll_attempts=1)
    rm.initialize()
    rm.start()

    paper.set_mark_price(SYMBOL, 90.0)
    rm.on_price_tick(
        SimpleNamespace(
            symbol=SYMBOL,
            last_price=90.0,
            exchange=EXCHANGE,
            raw_last_price="90.00000000",
        )
    )

    assert not pm.is_open(SYMBOL, exchange=EXCHANGE)
    # Triggered at 90, slipped 2% → 88.2
    assert position.exit_price == 88.2
    assert position.pnl == (88.2 - 100.0) * 10.0
