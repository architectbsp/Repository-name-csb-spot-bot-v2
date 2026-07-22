"""
BudgetedExchangeManager -- per-strategy virtual quote allotment on top of
a shared ExchangeManager (multi-strategy isolation).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType, OrderResult
from app.core.trading.models import TradeRequest, TradeSide


logger = logging.getLogger(__name__)


class BudgetedExchangeManager:
    """
    Proxies an ``ExchangeManager`` while capping reported free quote
    balance to a per-pipeline budget. Fills debit/credit the budget so
    each strategy's risk sizing stays independent of the others.
    """

    def __init__(
        self,
        inner: ExchangeManager,
        *,
        initial_budget: float,
        quote: str = "USDT",
        strategy_name: str = "pipeline",
    ) -> None:
        if initial_budget <= 0:
            raise ValueError("initial_budget must be positive")
        self._inner = inner
        self._quote = quote
        self._strategy_name = strategy_name
        self._cash = float(initial_budget)
        self._initial_budget = float(initial_budget)

    @property
    def inner(self) -> ExchangeManager:
        return self._inner

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def initial_budget(self) -> float:
        return self._initial_budget

    def get_quote_balance(
        self,
        exchange_type: ExchangeType,
        quote: str = "USDT",
    ) -> float:
        venue = float(self._inner.get_quote_balance(exchange_type, quote))
        if quote != self._quote:
            return venue
        return min(venue, self._cash)

    def execute_trade(
        self,
        exchange_type: ExchangeType,
        trade: TradeRequest,
    ):
        result = self._inner.execute_trade(exchange_type, trade)
        self._apply_fill(trade.side, result)
        return result

    def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        result = self._inner.place_market_buy(exchange_type, symbol, amount)
        self._apply_fill(TradeSide.BUY, result)
        return result

    def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        result = self._inner.place_market_sell(exchange_type, symbol, amount)
        self._apply_fill(TradeSide.SELL, result)
        return result

    def _apply_fill(self, side: TradeSide | str, result: OrderResult | Any) -> None:
        if result is None:
            return
        status = str(getattr(result, "status", "")).upper()
        if status not in {"CLOSED", "FILLED"}:
            return
        cost = getattr(result, "cost", None)
        avg = getattr(result, "average_price", None)
        qty = float(getattr(result, "filled_quantity", 0.0) or 0.0)
        if cost is None and avg is not None and qty:
            cost = float(avg) * qty
        if cost is None:
            return
        cost_f = float(cost)
        side_name = side.value if isinstance(side, TradeSide) else str(side)
        if side_name.upper() == "BUY":
            self._cash = max(0.0, self._cash - cost_f)
        else:
            self._cash += cost_f
        logger.debug(
            "[BUDGET:%s] side=%s cost=%.4f cash=%.4f",
            self._strategy_name,
            side_name,
            cost_f,
            self._cash,
        )

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
