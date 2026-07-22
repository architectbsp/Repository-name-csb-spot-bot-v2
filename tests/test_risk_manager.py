from decimal import Decimal
from types import SimpleNamespace

from app.core.exchange.models import OrderResult
from app.core.risk_manager import RiskManager
from app.core.trading.models import TradeSide


def make_config(max_open_positions=3):
    return SimpleNamespace(
        risk=SimpleNamespace(
            capital_per_trade_percent=10,
            max_daily_loss_percent=5,
            max_open_positions=max_open_positions,
            break_even_activation_percent=10.0,
            trailing_activation_percent=10.0,
            trailing_percent=5.0,
        )
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


def test_position_size():
    rm = RiskManager()
    rm.set_config(make_config())

    assert rm.calculate_position_size(1000) == 100
    assert rm.calculate_position_size(0) == 0


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
    rm.set_config(make_config())

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
        stop_loss_percent=5.0,
    )

    assert position is not None
    assert position.symbol == "BTCUSDT"
    assert position.entry_price == 100.0
    assert position.stop_price == 95.0
    assert position_manager.positions["BTCUSDT"] is position

    # The order was validated before it was sent to the exchange.
    assert len(order_validator.calls) == 1
    assert len(exchange_manager.executed_trades) == 1


def test_open_position_returns_none_when_order_not_filled():
    rm = RiskManager()
    rm.set_config(make_config())

    rm.set_exchange_manager(
        DummyExchangeManager(balance=1000.0, fill_status="OPEN", fill_ratio=0.0)
    )
    rm.set_order_validator(DummyOrderValidator())

    position_manager = DummyPositionManager()
    rm.set_position_manager(position_manager)

    position = rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
        stop_loss_percent=5.0,
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
        stop_loss_percent=5.0,
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
        stop_loss_percent=5.0,
    )

    assert position is not None
    assert position.exchange == "BYBIT"


class DummyPositionsBySymbol:
    def __init__(self, position):
        self._position = position
        self.closed = []

    def get(self, symbol):
        return self._position if symbol == self._position.symbol else None

    def close(self, symbol, *, exit_price, reason):
        self.closed.append((symbol, exit_price, reason))


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
    assert positions.closed == [("BTCUSDT", 100.0, "STOP_LOSS")]


def test_open_position_returns_none_when_dependencies_missing():
    rm = RiskManager()
    rm.set_config(make_config())

    assert rm.open_position(
        exchange_type="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
        stop_loss_percent=5.0,
    ) is None
