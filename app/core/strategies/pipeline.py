"""
StrategyPipeline -- one strategy + its own WatchList / RiskManager /
PositionManager / budgeted exchange view.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config.settings import AppSettings
from app.core.exchange.budgeted import BudgetedExchangeManager, SharedMarketOrderGate
from app.core.exchange.manager import ExchangeManager
from app.core.persistence.service import PersistenceService
from app.core.position_manager import PositionManager
from app.core.risk_manager import RiskManager
from app.core.services.order_validator import OrderValidator
from app.core.services.trade_journal import TradeJournal
from app.core.strategies.base import BaseStrategy
from app.core.strategies.factory import (
    apply_strategy_preset,
    create_strategy,
    pipeline_budget,
)
from app.core.watch_list import WatchList


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StrategyPipeline:
    """Isolated parallel trading lane for one named strategy."""

    name: str
    strategy: BaseStrategy
    watch_list: WatchList
    risk_manager: RiskManager
    position_manager: PositionManager
    trade_journal: TradeJournal
    config: AppSettings
    exchange_manager: BudgetedExchangeManager | ExchangeManager
    budget: float

    def handle_scan_result(self, tickers) -> int:
        return self.watch_list.handle_scan_result(tickers)

    def handle_price_update(self, ticker) -> None:
        self.watch_list.handle_price_update(ticker)
        self.risk_manager.on_price_tick(ticker)

    def handle_position_closed(self, event) -> None:
        self.watch_list.handle_position_closed(event)
        self.position_manager.handle_position_closed(event)

    def on_config_updated(self, event) -> None:
        self.strategy.on_config_updated(event)
        self.risk_manager.on_config_updated(event)

    def initialize(self) -> None:
        self.strategy.set_config(self.config)
        self.watch_list.set_config(self.config)
        self.risk_manager.set_config(self.config)
        for module in (
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.initialize()

    def start(self) -> None:
        for module in (
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.start()

    def stop(self) -> None:
        for module in (
            self.strategy,
            self.risk_manager,
            self.position_manager,
            self.watch_list,
        ):
            module.stop()

    def shutdown(self) -> None:
        for module in (
            self.strategy,
            self.risk_manager,
            self.position_manager,
            self.watch_list,
        ):
            module.shutdown()


def build_strategy_pipeline(
    name: str,
    shared_exchange: ExchangeManager,
    *,
    base_config: AppSettings | None = None,
    persistence: PersistenceService | None = None,
    budget: float | None = None,
    apply_preset: bool = True,
    strategy: BaseStrategy | None = None,
    order_gate: SharedMarketOrderGate | None = None,
) -> StrategyPipeline:
    """
    Builds an isolated pipeline. Orders still hit ``shared_exchange``;
    sizing/treasury are gated by ``BudgetedExchangeManager``.
    """
    config = (
        apply_strategy_preset(base_config, name)
        if apply_preset
        else (base_config or AppSettings())
    )
    allocated = float(budget if budget is not None else pipeline_budget(name))
    budgeted = BudgetedExchangeManager(
        shared_exchange,
        initial_budget=allocated,
        strategy_name=name,
        order_gate=order_gate,
    )

    persistence = persistence or PersistenceService.from_url("sqlite:///:memory:")
    position_manager = PositionManager()
    position_manager.set_repository(persistence.position_repository())

    trade_journal = TradeJournal()
    trade_journal.set_repository(persistence.trade_journal_repository())

    order_validator = OrderValidator(budgeted)  # type: ignore[arg-type]

    risk_manager = RiskManager()
    risk_manager.set_exchange(budgeted)
    risk_manager.set_exchange_manager(budgeted)
    risk_manager.set_position_manager(position_manager)
    risk_manager.set_order_validator(order_validator)
    risk_manager.set_trade_journal(trade_journal)
    risk_manager.set_config(config)

    strategy_obj = strategy or create_strategy(name)
    strategy_obj.set_risk_manager(risk_manager)
    strategy_obj.set_position_manager(position_manager)
    strategy_obj.set_trade_journal(trade_journal)
    strategy_obj.set_config(config)

    watch_list = WatchList()
    watch_list.set_exchange(budgeted)
    watch_list.set_strategy(strategy_obj)
    watch_list.set_config(config)

    logger.info(
        "[PIPELINE] Built %s (budget=%.2f stop=%.2f%% max_pos=%d)",
        name,
        allocated,
        config.risk.stop_loss_percent,
        config.risk.max_open_positions,
    )

    return StrategyPipeline(
        name=name,
        strategy=strategy_obj,
        watch_list=watch_list,
        risk_manager=risk_manager,
        position_manager=position_manager,
        trade_journal=trade_journal,
        config=config,
        exchange_manager=budgeted,
        budget=allocated,
    )
