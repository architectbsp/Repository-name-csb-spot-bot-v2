"""
CLI entry: ``python -m app.core.backtest``

Examples:
  python -m app.core.backtest --csv ./data/btc_1h.csv --symbol BTC/USDT
  python -m app.core.backtest --download BTC/USDT --timeframe 1h --days 30
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from app.core.backtest.data import download_binance_klines, load_ohlcv_csv
from app.core.backtest.engine import BacktestEngine, format_report
from app.core.config.settings import AppSettings


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
    # Liquidity-only sizing is more deterministic for offline runs when
    # ATR history is thin at the start of the series.
    config.risk.position_sizing_mode = 0

    engine = BacktestEngine(
        candles,
        symbol=symbol,
        config=config,
        initial_balance=args.balance,
    )
    result = engine.run()
    print(format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
