"""
Trading domain models.

This module intentionally contains only domain data structures.
Business logic will be added in future integration steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.core.exchange.spot_guard import (
    ORDER_TYPE_MARKET,
    SpotOnlyViolationException,
    assert_market_order_type,
)


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Sprint 13 -- only MARKET is legal for this spot bot."""

    MARKET = ORDER_TYPE_MARKET


@dataclass(slots=True, frozen=True)
class TradeRequest:
    symbol: str
    side: TradeSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET

    def __post_init__(self) -> None:
        # Frozen dataclass: validate via assert helpers.
        value = (
            self.order_type.value
            if isinstance(self.order_type, OrderType)
            else self.order_type
        )
        try:
            assert_market_order_type(value)
        except SpotOnlyViolationException:
            raise
        if self.order_type != OrderType.MARKET:
            raise SpotOnlyViolationException(
                f"TradeRequest.order_type must be MARKET, got {self.order_type!r}"
            )
