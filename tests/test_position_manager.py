from datetime import datetime

from app.core.position_manager import (
    MAX_OPEN_POSITIONS,
    Position,
    PositionManager,
    PositionState,
)


def make_position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        entry_price=100.0,
        quantity=1.0,
        opened_at=datetime.utcnow(),
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
