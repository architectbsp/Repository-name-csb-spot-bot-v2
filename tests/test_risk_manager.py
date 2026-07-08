from types import SimpleNamespace

from app.core.risk_manager import RiskManager


def make_config():
    return SimpleNamespace(
        risk=SimpleNamespace(
            capital_per_trade_percent=10,
            max_daily_loss_percent=5,
            max_open_positions=3,
        )
    )


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
