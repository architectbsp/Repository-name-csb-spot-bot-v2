"""
OHLCV loaders for the backtest engine: CSV files or Binance public klines.
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import ccxt

from app.core.domain.candle import Candle


logger = logging.getLogger(__name__)


def load_ohlcv_csv(path: str | Path) -> list[Candle]:
    """
    Loads candles from CSV.

    Accepted headers (case-insensitive):
      timestamp|time|open_time, open, high, low, close, volume

    Timestamp may be epoch ms/seconds or ISO-8601. Rows without a header
    are treated as ``timestamp,open,high,low,close,volume``.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"OHLCV CSV not found: {file_path}")

    with file_path.open(newline="", encoding="utf-8") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = False

        candles: list[Candle] = []
        if has_header:
            for dict_row in csv.DictReader(handle):
                candle = _candle_from_row(dict_row)
                if candle is not None:
                    candles.append(candle)
        else:
            for cells in csv.reader(handle):
                if not cells or len(cells) < 6:
                    continue
                candles.append(
                    Candle(
                        timestamp=_parse_timestamp(cells[0]),
                        open=float(cells[1]),
                        high=float(cells[2]),
                        low=float(cells[3]),
                        close=float(cells[4]),
                        volume=float(cells[5]),
                    )
                )

    candles.sort(key=lambda c: c.timestamp)
    if not candles:
        raise ValueError(f"No candles loaded from {file_path}")
    return candles


def download_binance_klines(
    symbol: str,
    *,
    timeframe: str = "1h",
    since_ms: int | None = None,
    until_ms: int | None = None,
    limit: int = 1000,
    max_candles: int = 5000,
) -> list[Candle]:
    """
    Downloads public Binance spot OHLCV via ccxt (no API keys required).
    Paginates until ``until_ms`` or ``max_candles`` is reached.
    """
    client = ccxt.binance({"enableRateLimit": True})
    # Normalize compact symbols (BTCUSDT → BTC/USDT) when needed.
    markets = client.load_markets()
    resolved = symbol
    if symbol not in markets and "/" not in symbol:
        for quote in ("USDT", "USD", "USDC", "BUSD"):
            candidate = f"{symbol[:-len(quote)]}/{quote}" if symbol.endswith(quote) else None
            if candidate and candidate in markets:
                resolved = candidate
                break

    if since_ms is None:
        # Default: ~30 days of 1h bars (or equivalent for other TFs).
        tf_ms = int(client.parse_timeframe(timeframe) * 1000)
        since_ms = int(time.time() * 1000) - (tf_ms * min(max_candles, 720))

    candles: list[Candle] = []
    cursor = since_ms

    while len(candles) < max_candles:
        batch_limit = min(limit, max_candles - len(candles))
        rows = client.fetch_ohlcv(
            resolved,
            timeframe=timeframe,
            since=cursor,
            limit=batch_limit,
        )
        if not rows:
            break

        for row in rows:
            candle = Candle.from_ccxt_row(row)
            if until_ms is not None and candle.timestamp > until_ms:
                candles.sort(key=lambda c: c.timestamp)
                return candles
            candles.append(candle)

        last_ts = int(rows[-1][0])
        next_cursor = last_ts + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        if len(rows) < batch_limit:
            break

    # Deduplicate by timestamp (overlapping pages).
    by_ts = {c.timestamp: c for c in candles}
    ordered = sorted(by_ts.values(), key=lambda c: c.timestamp)
    logger.info(
        "[BACKTEST] Downloaded %d %s candles for %s",
        len(ordered),
        timeframe,
        resolved,
    )
    return ordered


def _candle_from_row(row: dict) -> Candle | None:
    normalized = {str(k).strip().lower(): v for k, v in row.items() if k}
    ts_key = next(
        (k for k in ("timestamp", "time", "open_time", "date") if k in normalized),
        None,
    )
    required = ("open", "high", "low", "close", "volume")
    if ts_key is None or any(k not in normalized for k in required):
        return None
    return Candle(
        timestamp=_parse_timestamp(normalized[ts_key]),
        open=float(normalized["open"]),
        high=float(normalized["high"]),
        low=float(normalized["low"]),
        close=float(normalized["close"]),
        volume=float(normalized["volume"]),
    )


def _parse_timestamp(value) -> int:
    if value is None:
        raise ValueError("Missing timestamp")
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts if ts >= 1_000_000_000_000 else ts * 1000

    text = str(value).strip()
    if text.isdigit():
        ts = int(text)
        return ts if ts >= 1_000_000_000_000 else ts * 1000

    # ISO-8601 → ms
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Unrecognized timestamp: {value!r}") from exc
    return int(dt.timestamp() * 1000)
