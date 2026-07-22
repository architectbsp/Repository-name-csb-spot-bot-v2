"""
MultiStrategyOrchestrator -- fans scan/ticker events out to N pipelines
running in parallel (independent watch lists, risk, and budgets).
"""

from __future__ import annotations

import logging

from app.core.config.settings import AppSettings
from app.core.exchange.manager import ExchangeManager
from app.core.persistence.service import PersistenceService
from app.core.strategies.factory import parse_enabled_strategies
from app.core.strategies.pipeline import StrategyPipeline, build_strategy_pipeline


logger = logging.getLogger(__name__)


class MultiStrategyOrchestrator:
    def __init__(self) -> None:
        self._pipelines: list[StrategyPipeline] = []

    @property
    def pipelines(self) -> list[StrategyPipeline]:
        return list(self._pipelines)

    def primary(self) -> StrategyPipeline | None:
        return self._pipelines[0] if self._pipelines else None

    def build(
        self,
        exchange_manager: ExchangeManager,
        *,
        base_config: AppSettings | None = None,
        persistence: PersistenceService | None = None,
        strategy_names: list[str] | None = None,
    ) -> list[StrategyPipeline]:
        names = strategy_names or parse_enabled_strategies()
        self._pipelines = [
            build_strategy_pipeline(
                name,
                exchange_manager,
                base_config=base_config,
                persistence=persistence,
            )
            for name in names
        ]
        logger.info(
            "[MULTI-STRATEGY] %d pipeline(s): %s",
            len(self._pipelines),
            ", ".join(p.name for p in self._pipelines),
        )
        return self.pipelines

    def handle_scan_result(self, tickers) -> int:
        total = 0
        for pipeline in self._pipelines:
            total += pipeline.handle_scan_result(tickers)
        return total

    def handle_price_update(self, ticker) -> None:
        for pipeline in self._pipelines:
            pipeline.handle_price_update(ticker)

    def handle_position_closed(self, event) -> None:
        for pipeline in self._pipelines:
            pipeline.handle_position_closed(event)

    def on_config_updated(self, event) -> None:
        for pipeline in self._pipelines:
            pipeline.on_config_updated(event)

    def initialize(self) -> None:
        for pipeline in self._pipelines:
            pipeline.initialize()

    def start(self) -> None:
        for pipeline in self._pipelines:
            pipeline.start()

    def stop(self) -> None:
        for pipeline in self._pipelines:
            pipeline.stop()

    def shutdown(self) -> None:
        for pipeline in self._pipelines:
            pipeline.shutdown()
