"""
BudgetedExchangeManager -- per-strategy virtual quote allotment on top of
a shared ExchangeManager (multi-strategy isolation).

Hard-enforces budget before live buys (reserve → submit → settle) and
optionally serializes same-market orders across pipelines via
``SharedMarketOrderGate``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.exchange.manager import ExchangeManager
from app.core.exchange.market_key import market_key
from app.core.exchange.models import ExchangeType, OrderResult
from app.core.trading.models import TradeRequest, TradeSide


logger = logging.getLogger(__name__)

# Extra headroom on estimated buy cost for fees / tiny slippage so a
# fill that lands slightly above mark does not overshoot the allotment.
_BUY_COST_BUFFER = 0.002


class BudgetExceededError(RuntimeError):
    """Raised when a BUY would exceed this pipeline's remaining budget."""


class MarketOrderInFlightError(RuntimeError):
    """Raised when another pipeline already has an order in flight for the market."""


class SharedMarketOrderGate:
    """
    Cross-pipeline in-flight guard keyed by ``market_key(exchange, symbol)``.

    Each RiskManager has its own OrderExecutionService; without this gate
    two strategies can submit the same venue symbol concurrently.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()

    def try_acquire(self, key: str) -> bool:
        with self._lock:
            if key in self._in_flight:
                return False
            self._in_flight.add(key)
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._in_flight.discard(key)


class BudgetedExchangeManager:
    """
    Proxies an ``ExchangeManager`` while capping reported free quote
    balance to a per-pipeline budget. Buys are rejected before they
    reach the venue when the estimated cost exceeds remaining cash.
    """

    def __init__(
        self,
        inner: ExchangeManager,
        *,
        initial_budget: float,
        quote: str = "USDT",
        strategy_name: str = "pipeline",
        order_gate: SharedMarketOrderGate | None = None,
        buy_cost_buffer: float = _BUY_COST_BUFFER,
    ) -> None:
        if initial_budget <= 0:
            raise ValueError("initial_budget must be positive")
        self._inner = inner
        self._quote = quote
        self._strategy_name = strategy_name
        self._cash = float(initial_budget)
        self._initial_budget = float(initial_budget)
        self._order_gate = order_gate
        self._buy_cost_buffer = max(0.0, float(buy_cost_buffer))
        self._budget_lock = threading.Lock()

    @property
    def inner(self) -> ExchangeManager:
        return self._inner

    @property
    def cash(self) -> float:
        with self._budget_lock:
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
        with self._budget_lock:
            return min(venue, self._cash)

    def execute_trade(
        self,
        exchange_type: ExchangeType,
        trade: TradeRequest,
    ):
        side = trade.side
        amount = float(trade.quantity)
        return self._run_gated_order(
            exchange_type,
            trade.symbol,
            side,
            amount,
            lambda: self._inner.execute_trade(exchange_type, trade),
        )

    def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
        params=None,
    ):
        return self._run_gated_order(
            exchange_type,
            symbol,
            TradeSide.BUY,
            float(amount),
            lambda: self._inner.place_market_buy(
                exchange_type, symbol, amount, params
            ),
        )

    def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
        params=None,
    ):
        return self._run_gated_order(
            exchange_type,
            symbol,
            TradeSide.SELL,
            float(amount),
            lambda: self._inner.place_market_sell(
                exchange_type, symbol, amount, params
            ),
        )

    def _run_gated_order(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        side: TradeSide | str,
        amount: float,
        submit,
    ):
        side_name = side.value if isinstance(side, TradeSide) else str(side)
        is_buy = side_name.upper() == "BUY"
        reserved = 0.0

        if is_buy:
            estimated = self._estimate_buy_cost(exchange_type, symbol, amount)
            reserved = self._reserve_buy(estimated)

        flight_key = market_key(exchange_type, symbol)
        acquired = False
        if self._order_gate is not None:
            acquired = self._order_gate.try_acquire(flight_key)
            if not acquired:
                if is_buy and reserved:
                    self._release_reservation(reserved)
                raise MarketOrderInFlightError(
                    f"Order already in flight for {flight_key} "
                    f"(strategy={self._strategy_name})"
                )

        try:
            result = submit()
        except Exception:
            if is_buy and reserved:
                self._release_reservation(reserved)
            raise
        finally:
            if acquired and self._order_gate is not None:
                self._order_gate.release(flight_key)

        if is_buy:
            self._settle_buy(reserved, result)
        else:
            self._apply_fill(side, result)
        return result

    def _estimate_buy_cost(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ) -> float:
        if amount <= 0:
            raise BudgetExceededError(
                f"Invalid buy amount {amount} for {symbol} "
                f"(strategy={self._strategy_name})"
            )
        price = self._resolve_mark_price(exchange_type, symbol)
        return float(amount) * price * (1.0 + self._buy_cost_buffer)

    def _resolve_mark_price(
        self,
        exchange_type: ExchangeType,
        symbol: str,
    ) -> float:
        # Prefer paper/live adapter mark cache when available.
        adapter = self._inner._get_exchange(exchange_type)
        last_prices = getattr(adapter, "_last_prices", None)
        if isinstance(last_prices, dict):
            cached = last_prices.get(symbol)
            if cached is not None and float(cached) > 0:
                return float(cached)

        tickers = adapter.fetch_tickers()
        ticker = (tickers or {}).get(symbol) or {}
        last = ticker.get("last") or ticker.get("close")
        if last is None or float(last) <= 0:
            raise BudgetExceededError(
                f"No mark price for {symbol}; cannot enforce budget "
                f"(strategy={self._strategy_name})"
            )
        return float(last)

    def _reserve_buy(self, estimated: float) -> float:
        with self._budget_lock:
            if estimated > self._cash + 1e-12:
                raise BudgetExceededError(
                    f"Pipeline budget exceeded for {self._strategy_name}: "
                    f"need {estimated:.8f} {self._quote}, have {self._cash:.8f}"
                )
            self._cash -= estimated
            logger.info(
                "[BUDGET:%s] reserved=%.8f remaining=%.8f",
                self._strategy_name,
                estimated,
                self._cash,
            )
            return estimated

    def _release_reservation(self, reserved: float) -> None:
        with self._budget_lock:
            self._cash += reserved
            logger.info(
                "[BUDGET:%s] reservation released=%.8f remaining=%.8f",
                self._strategy_name,
                reserved,
                self._cash,
            )

    def _settle_buy(self, reserved: float, result: OrderResult | Any) -> None:
        status = str(getattr(result, "status", "") or "").upper()
        filled = status in {"CLOSED", "FILLED"}
        actual = self._fill_cost(result) if filled else None

        with self._budget_lock:
            if not filled:
                self._cash += reserved
                logger.info(
                    "[BUDGET:%s] buy not filled; refunded=%.8f remaining=%.8f",
                    self._strategy_name,
                    reserved,
                    self._cash,
                )
                return

            if actual is None:
                # Keep the reservation as spent.
                return

            # reserved was debited already; adjust to actual fill cost.
            self._cash += reserved - actual
            if self._cash < 0:
                # Fill cost above estimate — clamp; next buys will fail.
                logger.warning(
                    "[BUDGET:%s] fill exceeded reserve (reserved=%.8f actual=%.8f)",
                    self._strategy_name,
                    reserved,
                    actual,
                )
                self._cash = 0.0

    def _apply_fill(self, side: TradeSide | str, result: OrderResult | Any) -> None:
        if result is None:
            return
        status = str(getattr(result, "status", "")).upper()
        if status not in {"CLOSED", "FILLED"}:
            return
        cost = self._fill_cost(result)
        if cost is None:
            return
        side_name = side.value if isinstance(side, TradeSide) else str(side)
        with self._budget_lock:
            if side_name.upper() == "BUY":
                self._cash = max(0.0, self._cash - cost)
            else:
                self._cash += cost
            logger.debug(
                "[BUDGET:%s] side=%s cost=%.4f cash=%.4f",
                self._strategy_name,
                side_name,
                cost,
                self._cash,
            )

    @staticmethod
    def _fill_cost(result: OrderResult | Any) -> float | None:
        cost = getattr(result, "cost", None)
        avg = getattr(result, "average_price", None)
        qty = float(getattr(result, "filled_quantity", 0.0) or 0.0)
        if cost is None and avg is not None and qty:
            cost = float(avg) * qty
        if cost is None:
            return None
        return float(cost)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
