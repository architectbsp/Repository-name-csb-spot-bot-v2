"""Backtest engine -- CSV load + Strategy/RiskManager paper replay."""

from pathlib import Path

from app.core.backtest.data import load_ohlcv_csv
from app.core.backtest.engine import BacktestEngine
from app.core.config.settings import AppSettings
from app.core.domain.candle import Candle


def _candle(ts: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000_000.0,
    )


def test_load_ohlcv_csv_with_header(tmp_path: Path):
    path = tmp_path / "ohlcv.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "1700000000000,100,101,99,100.5,10\n"
        "1700003600000,100.5,102,100,101,12\n",
        encoding="utf-8",
    )
    candles = load_ohlcv_csv(path)
    assert len(candles) == 2
    assert candles[0].open == 100.0
    assert candles[1].close == 101.0


def test_backtest_engine_runs_and_can_open_trade():
    """
    Path A: change_24h >= watch_percent puts the coin in WATCH_RISING,
    then a further +entry_percent recovery from that low triggers BUY.
    A later hard stop (-10%) closes the position so the report has trades.
    """
    config = AppSettings()
    config.strategy.watch_percent = 2.0
    config.strategy.entry_percent = 2.0
    config.risk.position_sizing_mode = 0
    config.risk.stop_loss_percent = 10.0
    config.strategy.trading_hours_enabled = 0

    # Bar 0: establish watch (price rises vs open → positive change_24h).
    # Bar 1: continue rise past entry_percent from watch low.
    # Bar 2: crash through hard stop.
    candles = [
        _candle(1_700_000_000_000, 100.0, 103.0, 100.0, 103.0),
        _candle(1_700_003_600_000, 103.0, 106.0, 103.0, 106.0),
        _candle(1_700_007_200_000, 106.0, 106.0, 90.0, 90.0),
    ]

    result = BacktestEngine(
        candles,
        symbol="BTC/USDT",
        config=config,
        initial_balance=10_000.0,
        fee_rate=0.0,
        change_lookback_bars=24,
    ).run()

    assert result.candles_processed == 3
    # At least one round-trip (entry + stop) should appear in analytics.
    assert result.report.total_trades >= 1
    assert result.final_quote_balance != result.initial_quote_balance or (
        result.report.total_pnl != 0
    )
