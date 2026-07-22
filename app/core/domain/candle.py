"""
Sprint 6 -- Coin charts: a single OHLCV candle, normalized from whatever
shape ccxt's `fetch_ohlcv` returns (a 6-element list per candle:
[timestamp_ms, open, high, low, close, volume]).
"""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Candle:
    timestamp: int  # epoch milliseconds, as returned by the exchange
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ccxt_row(cls, row: list) -> "Candle":
        return cls(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
