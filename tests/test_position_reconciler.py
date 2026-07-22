from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.core.domain.position import Position, PositionState
from app.core.exchange.models import ExchangeType
from app.core.services.position_reconciler import PositionReconciler


def _open_position(symbol="BTCUSDT", qty=1.0):
    return Position(
        symbol=symbol,
        entry_price=100.0,
        quantity=qty,
        opened_at=datetime.now(timezone.utc),
        state=PositionState.OPEN,
        exchange=ExchangeType.BINANCE,
    )


def test_reconcile_ok_when_balance_covers_position():
    pm = MagicMock()
    pm.get_open_positions.return_value = [_open_position(qty=1.0)]
    em = MagicMock()
    em.get_base_balance.return_value = 1.0
    oe = MagicMock()
    bus = MagicMock()

    reconciler = PositionReconciler()
    reconciler.set_position_manager(pm)
    reconciler.set_exchange_manager(em)
    reconciler.set_order_execution(oe)
    reconciler.set_event_bus(bus)

    assert reconciler.reconcile_once() == []
    oe.quarantine.assert_not_called()
    bus.publish.assert_not_called()


def test_reconcile_mismatch_quarantines_and_publishes():
    pm = MagicMock()
    pm.get_open_positions.return_value = [_open_position(qty=1.0)]
    em = MagicMock()
    em.get_base_balance.return_value = 0.1  # far below tolerance
    oe = MagicMock()
    bus = MagicMock()

    reconciler = PositionReconciler()
    reconciler.set_position_manager(pm)
    reconciler.set_exchange_manager(em)
    reconciler.set_order_execution(oe)
    reconciler.set_event_bus(bus)

    mismatches = reconciler.reconcile_once()
    assert len(mismatches) == 1
    assert mismatches[0]["local_quantity"] == 1.0
    assert mismatches[0]["exchange_free"] == 0.1
    oe.quarantine.assert_called_once()
    topics = [c.args[0] for c in bus.publish.call_args_list]
    assert "position.reconcile_mismatch" in topics
    assert "order.needs_manual_review" in topics
