"""
CLI entry: ``python -m app.core.backtest``

Examples:
  python -m app.core.backtest --csv ./data/btc_1h.csv --symbol BTC/USDT
  python -m app.core.backtest --download BTC/USDT --timeframe 1h --days 30
  python -m app.core.backtest --csv ./data.csv --optimize grid \\
      --param risk.stop_loss_percent:0.5:2.0:0.5 \\
      --param strategy.watch_percent:2:4:1
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from app.core.backtest.data import download_binance_klines, load_ohlcv_csv
from app.core.backtest.engine import BacktestEngine, format_report
from app.core.backtest.optimizer import ParamRange, ParameterOptimizer
from app.core.config.settings import AppSettings


def _parse_param(spec: str) -> ParamRange:
    """
    Formats:
      path:start:stop:step   (grid)
      path:start:stop        (GA continuous)
    """
    parts = spec.split(":")
    if len(parts) not in {3, 4}:
        raise argparse.ArgumentTypeError(
            f"Invalid --param {spec!r}; use path:start:stop[:step]"
        )
    path, start_s, stop_s = parts[0], parts[1], parts[2]
    step = float(parts[3]) if len(parts) == 4 else None
    return ParamRange(
        path=path,
        start=float(start_s),
        stop=float(stop_s),
        step=step,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CSB Spot Bot backtest engine")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Path to OHLCV CSV")
    source.add_argument(
        "--download",
        metavar="SYMBOL",
        help="Download Binance public klines for SYMBOL (e.g. BTC/USDT)",
    )
    parser.add_argument("--symbol", default="BTC/USDT", help="Market symbol")
    parser.add_argument("--timeframe", default="1h", help="Kline timeframe")
    parser.add_argument("--days", type=int, default=30, help="Lookback days for download")
    parser.add_argument(
        "--balance",
        type=float,
        default=10_000.0,
        help="Paper starting quote balance",
    )
    parser.add_argument(
        "--strategy",
        default="dip_hunter",
        help="Strategy name (dip_hunter|momentum|breakout|scalper)",
    )
    parser.add_argument(
        "--watch-percent",
        type=float,
        default=None,
        help="Override strategy.watch_percent",
    )
    parser.add_argument(
        "--entry-percent",
        type=float,
        default=None,
        help="Override strategy.entry_percent",
    )
    parser.add_argument(
        "--optimize",
        choices=("grid", "genetic"),
        default=None,
        help="Run parameter optimizer (max Profit Factor)",
    )
    parser.add_argument(
        "--param",
        action="append",
        type=_parse_param,
        default=[],
        help="Search range path:start:stop[:step] (repeatable)",
    )
    parser.add_argument("--population", type=int, default=12)
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.csv:
        candles = load_ohlcv_csv(args.csv)
        symbol = args.symbol
    else:
        symbol = args.download
        since_ms = int(time.time() * 1000) - args.days * 86_400_000
        candles = download_binance_klines(
            symbol,
            timeframe=args.timeframe,
            since_ms=since_ms,
        )

    config = AppSettings()
    if args.watch_percent is not None:
        config.strategy.watch_percent = args.watch_percent
    if args.entry_percent is not None:
        config.strategy.entry_percent = args.entry_percent
    config.risk.position_sizing_mode = 0

    if args.optimize:
        if not args.param:
            parser.error("--optimize requires at least one --param")
        opt = ParameterOptimizer(
            candles,
            base_config=config,
            symbol=symbol,
            initial_balance=args.balance,
            strategy_name=args.strategy,
            fee_rate=0.0,
        )
        result = opt.optimize(
            args.param,
            method=args.optimize,
            population_size=args.population,
            generations=args.generations,
        )
        print(f"Optimizer ({result.method}) best Profit Factor: {result.best.profit_factor}")
        print(f"Best params: {result.best_params}")
        print(f"Trades: {result.best.total_trades}  PnL: {result.best.total_pnl:.4f}")
        print(f"Trials evaluated: {len(result.trials)}")
        if result.best.result is not None:
            print(format_report(result.best.result))
        return 0

    engine = BacktestEngine(
        candles,
        symbol=symbol,
        config=config,
        initial_balance=args.balance,
        strategy_name=args.strategy,
    )
    backtest_result = engine.run()
    print(format_report(backtest_result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
