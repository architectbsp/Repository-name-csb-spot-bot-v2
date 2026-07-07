from __future__ import annotations

from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType
from app.core.trading.models import TradeRequest


class OrderValidator:
    def __init__(
        self,
        exchange_manager: ExchangeManager,
    ) -> None:
        self._exchange_manager = exchange_manager

    def validate(
        self,
        exchange_type: ExchangeType,
        trade: TradeRequest,
    ) -> TradeRequest:
        metadata = self._exchange_manager.get_market_metadata(
            exchange_type,
            trade.symbol,
        )

        if not metadata.active:
            raise ValueError(
                f"Market is inactive: {trade.symbol}"
            )

        normalized_amount = self._exchange_manager.normalize_amount(
            exchange_type,
            trade.symbol,
            float(trade.quantity),
        )

        if metadata.minimum_amount is not None:
            if normalized_amount < metadata.minimum_amount:
                raise ValueError(
                    f"Minimum amount is {metadata.minimum_amount}"
                )

        return TradeRequest(
            symbol=trade.symbol,
            side=trade.side,
            quantity=type(trade.quantity)(str(normalized_amount)),
        )
