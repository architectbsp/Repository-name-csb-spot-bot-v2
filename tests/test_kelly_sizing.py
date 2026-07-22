from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.core.domain.trade_journal import STATUS_CLOSED, TradeJournalEntry
from app.core.risk_manager import RiskManager
from app.core.services.trade_journal import TradeJournal


class _Journal:
    def __init__(self, entries):
        self._entries = entries

    def list_all(self):
        return list(self._entries)


def _closed(pnl, *, pnl_percent=None):
    now = datetime.now(UTC)
    return TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=now - timedelta(hours=1),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status=STATUS_CLOSED,
        exit_time=now,
        exit_price=100.0 + pnl,
        exit_reason="TRAILING_STOP",
        pnl=pnl,
        pnl_percent=pnl_percent if pnl_percent is not None else pnl,
    )


def test_kelly_mode_sizes_from_closed_trade_stats():
    # 7 wins of +10, 3 losses of -5 → W=0.7, R=2, f*=0.55
    # half-Kelly 0.5 * 0.55 = 0.275 → hard-capped at 0.25 → size=2500
    entries = [_closed(10.0) for _ in range(7)] + [_closed(-5.0) for _ in range(3)]
    rm = RiskManager()
    rm.set_config(
        SimpleNamespace(
            risk=SimpleNamespace(
                max_balance_utilization_percent=99.5,
                max_volume_share_percent=100.0,  # don't bind on liquidity
                position_sizing_mode=4,
                risk_per_trade_percent=1.0,
                stop_loss_percent=10.0,
                atr_period=14,
                atr_multiplier=2.0,
                volatility_target_percent=0.0,
                volatility_lookback=20,
                kelly_fraction=0.5,
                kelly_min_trades=10,
            )
        )
    )
    rm.set_trade_journal(_Journal(entries))

    size = rm.calculate_position_size(10_000, volume_24h=1_000_000_000)
    assert abs(size - 2_500.0) < 1e-6


def test_kelly_mode_falls_back_when_too_few_trades():
    rm = RiskManager()
    rm.set_config(
        SimpleNamespace(
            risk=SimpleNamespace(
                max_balance_utilization_percent=99.5,
                max_volume_share_percent=0.1,
                position_sizing_mode=4,
                risk_per_trade_percent=1.0,
                stop_loss_percent=10.0,
                atr_period=14,
                atr_multiplier=2.0,
                volatility_target_percent=0.0,
                volatility_lookback=20,
                kelly_fraction=0.5,
                kelly_min_trades=10,
            )
        )
    )
    journal = TradeJournal()
    rm.set_trade_journal(journal)

    # No closed trades → only safety caps (balance * 99.5%).
    size = rm.calculate_position_size(1_000, volume_24h=50_000_000)
    assert size == 995.0
