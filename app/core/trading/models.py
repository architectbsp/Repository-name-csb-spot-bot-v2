"""
Trading domain models.

This module intentionally contains only domain data structures.
Business logic will be added in future integration steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(slots=True, frozen=True)
class TradeRequest:
    symbol: str
    side: TradeSide
    quantity: Decimal
