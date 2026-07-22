"""
BaseStrategy -- shared lifecycle and dependency wiring for every
named strategy (Dip Hunter, Momentum, Breakout, Scalper).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.core.exchange.market_key import market_key
from app.core.watch_list import WatchState


def strategy_config(config) -> Any:
    return getattr(config, "strategy", config)


def coin_key(ticker) -> str:
    return market_key(getattr(ticker, "exchange", None), ticker.symbol)


class BaseStrategy(ABC):
    """
    Entry-signal only. RiskManager owns sizing, validation and orders
    (docs/BUSINESS_RULES.md #11 / #12).
    """

    name: str = "base"

    _DEPENDENCY_NAMES = (
        "risk_manager",
        "position_manager",
        "trade_journal",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False
        self._risk_manager = None
        self._position_manager = None
        self._trade_journal = None
        self._config = None

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError(f"{self.name} strategy is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def set_risk_manager(self, risk_manager) -> None:
        self._risk_manager = risk_manager

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def set_config(self, config) -> None:
        self._config = config

    def on_config_updated(self, event) -> None:
        return None

    @abstractmethod
    def on_ticker(self, watch_list, ticker) -> None:
        ...

    def _position_already_open(self, ticker) -> bool:
        return (
            self._position_manager is not None
            and self._position_manager.is_open(
                ticker.symbol,
                exchange=ticker.exchange,
            )
        )

    def _try_open_position(
        self,
        watch_list,
        ticker,
        *,
        coin: dict,
        entry_reason: str,
    ):
        key = coin_key(ticker)
        watch_list.promote_to_buy_pending(key, ticker.last_price)

        if self._risk_manager is None:
            watch_list.cancel_buy_pending(key)
            return None

        position = self._risk_manager.open_position(
            exchange_type=ticker.exchange,
            symbol=ticker.symbol,
            price=ticker.last_price,
            volume_24h=ticker.volume_24h,
        )

        if position is None:
            watch_list.cancel_buy_pending(key)
            return None

        watch_list.promote_to_position_open(
            key,
            position.entry_price,
            position.stop_price,
        )
        self._record_journal_entry(
            coin,
            ticker,
            position,
            entry_reason=entry_reason,
        )
        return position

    def _record_journal_entry(
        self,
        coin,
        ticker,
        position,
        *,
        entry_reason: str,
    ) -> None:
        if self._trade_journal is None:
            return

        watch_started_at = coin.get("watch_started_at")
        wait_minutes = None
        if watch_started_at is not None:
            wait_minutes = (
                datetime.now(UTC) - watch_started_at
            ).total_seconds() / 60.0

        exchange_name = getattr(ticker.exchange, "name", ticker.exchange)
        cfg = strategy_config(self._config)

        entry_conditions = {
            "strategy": self.name,
            "entry_path": entry_reason,
            "volume_24h": getattr(ticker, "volume_24h", None),
            "last_price": getattr(ticker, "last_price", None),
            "change_24h": getattr(ticker, "change_24h", None),
            "min_volume_usd": getattr(cfg, "min_volume_usd", None),
            "watch_percent": getattr(cfg, "watch_percent", None),
            "entry_percent": getattr(cfg, "entry_percent", None),
        }

        wallet_quote_free = None
        if self._risk_manager is not None:
            try:
                wallet_quote_free = self._risk_manager.get_quote_balance(
                    ticker.exchange,
                )
            except Exception:
                wallet_quote_free = None

        self._trade_journal.record_entry(
            symbol=ticker.symbol,
            exchange=exchange_name,
            entry_price=position.entry_price,
            quantity=position.quantity,
            entry_reason=entry_reason,
            watch_started_at=watch_started_at,
            wait_minutes=wait_minutes,
            rise_events=coin.get("rise_count", 0),
            fall_events=coin.get("fall_count", 0),
            entry_conditions=entry_conditions,
            wallet_quote_free=wallet_quote_free,
        )

    def _handle_position_open(self, watch_list, ticker) -> None:
        if self._position_manager is None:
            return

        position = self._position_manager.get(
            ticker.symbol,
            exchange=ticker.exchange,
        )
        if position is None:
            return

        if ticker.last_price > position.entry_price:
            watch_list.update_highest_price(
                coin_key(ticker),
                ticker.last_price,
            )
