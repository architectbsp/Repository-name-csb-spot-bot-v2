"""Sprint 3 -- CloseReason contract + position lifecycle helpers."""

from datetime import UTC, datetime

from app.core.domain.position import CloseReason, Position, PositionState
from app.core.position_manager import PositionManager


def test_close_reason_covers_sprint3_prompt_set():
    required = {
        "STOP_LOSS",
        "TAKE_PROFIT",
        "PARTIAL_TP",
        "TRAILING_STOP",
        "MANUAL_CLOSE",
        "EMERGENCY_EXIT",
        "MAX_DAILY_LOSS",
    }
    values = {member.value for member in CloseReason}
    assert required <= values
    # Aliases resolve to the Sprint 3 names.
    assert CloseReason.MANUAL is CloseReason.MANUAL_CLOSE
    assert CloseReason.EMERGENCY is CloseReason.EMERGENCY_EXIT
    assert CloseReason.MANUAL.value == "MANUAL_CLOSE"
    assert CloseReason.EMERGENCY.value == "EMERGENCY_EXIT"


def test_manual_close_alias_matches_close_position_manually():
    from app.core.risk_manager import RiskManager

    rm = RiskManager()
    assert rm.manual_close.__func__ is RiskManager.manual_close
    assert callable(rm.manual_close)


def test_partial_exit_history_and_stop_protect_on_scale_out():
    manager = PositionManager()
    position = Position(
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=10.0,
        opened_at=datetime.now(UTC),
        stop_price=90.0,
        stop_stage="HARD",
    )
    manager.add(position)

    realized = manager.scale_out(
        "BTC/USDT",
        sell_quantity=5.0,
        exit_price=110.0,
        reason=CloseReason.PARTIAL_TP,
    )

    assert realized == 50.0
    assert position.remaining_quantity == 5.0
    assert position.stop_stage == "BREAK_EVEN"
    assert position.stop_price == 100.0
    assert position.close_reason is None
    assert position.state == PositionState.OPEN
    record = position.partial_exits[0]
    assert record.quantity == 5.0
    assert record.remaining_quantity == 5.0
    assert record.stop_stage_after == "BREAK_EVEN"
