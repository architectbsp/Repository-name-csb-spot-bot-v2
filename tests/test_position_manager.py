from datetime import UTC, datetime

from app.core.domain.position import Position, PositionState
from app.core.position_manager import MAX_OPEN_POSITIONS, PositionManager


def make_position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        entry_price=100.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        stop_price=95.0,
    )


def test_add_position():
    manager = PositionManager()

    assert manager.add(make_position("BTCUSDT"))
    assert manager.contains("BTCUSDT")
    assert manager.size() == 1


def test_duplicate_position_rejected():
    manager = PositionManager()

    manager.add(make_position("BTCUSDT"))

    assert manager.add(make_position("BTCUSDT")) is False
    assert manager.size() == 1


def test_remove_position():
    manager = PositionManager()

    manager.add(make_position("BTCUSDT"))

    assert manager.remove("BTCUSDT")
    assert not manager.contains("BTCUSDT")
    assert manager.is_empty()


def test_close_position():
    manager = PositionManager()

    manager.add(make_position("BTCUSDT"))

    assert manager.close("BTCUSDT")
    assert not manager.is_open("BTCUSDT")

    position = manager.get("BTCUSDT")
    assert position.state == PositionState.CLOSED


def test_open_position_count():
    manager = PositionManager()

    manager.add(make_position("BTCUSDT"))
    manager.add(make_position("ETHUSDT"))

    manager.close("ETHUSDT")

    assert manager.open_count() == 1


def test_max_open_positions_limit():
    manager = PositionManager()

    for i in range(MAX_OPEN_POSITIONS):
        assert manager.add(make_position(f"COIN{i}"))

    assert manager.add(make_position("OVERFLOW")) is False


def test_clear_positions():
    manager = PositionManager()

    manager.add(make_position("BTCUSDT"))
    manager.add(make_position("ETHUSDT"))

    manager.clear()

    assert manager.is_empty()
    assert manager.size() == 0


def test_scale_out_reduces_quantity_and_banks_realized_pnl():
    manager = PositionManager()
    manager.add(make_position("BTCUSDT"))

    realized = manager.scale_out("BTCUSDT", sell_quantity=0.4, exit_price=110.0)

    position = manager.get("BTCUSDT")
    assert realized == (110.0 - 100.0) * 0.4
    assert position.quantity == 0.6
    assert position.realized_pnl == (110.0 - 100.0) * 0.4
    assert position.partial_exits_taken == 1
    assert position.state == PositionState.OPEN


def test_scale_out_rejects_selling_the_full_remaining_quantity():
    manager = PositionManager()
    manager.add(make_position("BTCUSDT"))

    # Selling 100% (or more) of the remaining quantity must go through
    # close() instead -- scale_out() must never leave a position open
    # with 0 quantity.
    assert manager.scale_out("BTCUSDT", sell_quantity=1.0, exit_price=110.0) is None
    assert manager.get("BTCUSDT").quantity == 1.0
    assert manager.get("BTCUSDT").state == PositionState.OPEN


def test_scale_out_returns_none_for_unknown_or_closed_position():
    manager = PositionManager()
    manager.add(make_position("BTCUSDT"))
    manager.close("BTCUSDT")

    assert manager.scale_out("BTCUSDT", sell_quantity=0.1, exit_price=110.0) is None
    assert manager.scale_out("NOPE", sell_quantity=0.1, exit_price=110.0) is None


def test_close_pnl_includes_any_earlier_scale_out_realized_pnl():
    manager = PositionManager()
    manager.add(make_position("BTCUSDT"))

    # Partial exit at a profit, then close out the remainder at a loss --
    # the final position.pnl must reflect BOTH legs of the trade.
    manager.scale_out("BTCUSDT", sell_quantity=0.5, exit_price=120.0)
    manager.close("BTCUSDT", exit_price=90.0)

    position = manager.get("BTCUSDT")
    partial_pnl = (120.0 - 100.0) * 0.5
    final_pnl = (90.0 - 100.0) * 0.5
    assert position.pnl == partial_pnl + final_pnl
    assert position.state == PositionState.CLOSED


def test_initialize_start_stop_shutdown():
    manager = PositionManager()

    manager.initialize()
    assert manager.is_initialized()

    manager.start()
    assert manager.is_running()

    manager.stop()
    assert not manager.is_running()

    manager.shutdown()
    assert not manager.is_initialized()
