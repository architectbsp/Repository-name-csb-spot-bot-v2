"""Named trading strategies + parallel pipeline orchestration."""

from app.core.strategies.base import BaseStrategy
from app.core.strategies.breakout import BreakoutStrategy
from app.core.strategies.dip_hunter import DipHunterStrategy
from app.core.strategies.factory import (
    create_strategy,
    parse_enabled_strategies,
    supported_strategy_names,
)
from app.core.strategies.momentum import MomentumStrategy
from app.core.strategies.orchestrator import MultiStrategyOrchestrator
from app.core.strategies.pipeline import StrategyPipeline, build_strategy_pipeline
from app.core.strategies.scalper import ScalperStrategy

__all__ = [
    "BaseStrategy",
    "BreakoutStrategy",
    "DipHunterStrategy",
    "MomentumStrategy",
    "MultiStrategyOrchestrator",
    "ScalperStrategy",
    "StrategyPipeline",
    "build_strategy_pipeline",
    "create_strategy",
    "parse_enabled_strategies",
    "supported_strategy_names",
]
