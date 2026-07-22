"""Parameter optimizer -- grid / genetic over BacktestEngine."""

from app.core.backtest.optimizer import (
    ParamRange,
    ParameterOptimizer,
    apply_params,
    profit_factor_fitness,
)
from app.core.config.settings import AppSettings
from app.core.domain.candle import Candle
from app.core.domain.performance import PerformanceReport
from datetime import UTC, datetime

from app.core.backtest.engine import BacktestResult
from app.core.exchange.models import ExchangeType


def _candle(ts: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=1e6)


def _series() -> list[Candle]:
    # Same shape as backtest smoke: rise into entry, then stop-out.
    return [
        _candle(1_700_000_000_000, 100.0, 103.0, 100.0, 103.0),
        _candle(1_700_003_600_000, 103.0, 106.0, 103.0, 106.0),
        _candle(1_700_007_200_000, 106.0, 106.0, 90.0, 90.0),
    ]


def test_apply_params_sets_dotted_paths():
    cfg = apply_params(
        AppSettings(),
        {
            "risk.stop_loss_percent": 1.5,
            "strategy.watch_percent": 2.0,
        },
    )
    assert cfg.risk.stop_loss_percent == 1.5
    assert cfg.strategy.watch_percent == 2.0


def test_grid_search_picks_trial_with_params():
    config = AppSettings()
    config.strategy.watch_percent = 2.0
    config.strategy.entry_percent = 2.0
    config.risk.position_sizing_mode = 0
    config.strategy.trading_hours_enabled = 0

    opt = ParameterOptimizer(
        _series(),
        base_config=config,
        fee_rate=0.0,
        strategy_name="dip_hunter",
    )
    result = opt.optimize(
        [
            ParamRange("risk.stop_loss_percent", 5.0, 15.0, step=5.0),
        ],
        method="grid",
    )

    assert result.method == "grid"
    assert len(result.trials) == 3
    assert "risk.stop_loss_percent" in result.best_params
    assert result.best.fitness == max(t.fitness for t in result.trials)


def test_genetic_runs_and_returns_best():
    config = AppSettings()
    config.strategy.watch_percent = 2.0
    config.strategy.entry_percent = 2.0
    config.risk.position_sizing_mode = 0

    opt = ParameterOptimizer(
        _series(),
        base_config=config,
        fee_rate=0.0,
    )
    result = opt.optimize(
        [
            ParamRange("risk.stop_loss_percent", 5.0, 15.0, step=5.0),
            ParamRange("strategy.entry_percent", 1.0, 3.0, step=1.0),
        ],
        method="genetic",
        population_size=4,
        generations=2,
        seed=1,
    )
    assert result.best is not None
    assert len(result.trials) >= 4


def test_profit_factor_fitness_handles_none_and_inf():
    empty = PerformanceReport(
        generated_at=datetime.now(UTC),
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_percent=0.0,
        average_profit=0.0,
        average_loss=0.0,
        total_pnl=0.0,
        expectancy=0.0,
        profit_factor=None,
        sharpe_ratio=None,
        max_drawdown=0.0,
        max_drawdown_percent=0.0,
        recovery_factor=None,
    )
    result = BacktestResult(
        report=empty,
        candles_processed=0,
        symbol="BTC/USDT",
        exchange=ExchangeType.BINANCE,
        final_quote_balance=0.0,
        initial_quote_balance=0.0,
    )
    assert profit_factor_fitness(result) == 0.0
