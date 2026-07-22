"""Strategy registry / factory + per-strategy default knobs."""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from dataclasses import dataclass

from app.core.config.settings import AppSettings
from app.core.strategies.base import BaseStrategy
from app.core.strategies.breakout import BreakoutStrategy
from app.core.strategies.dip_hunter import DipHunterStrategy
from app.core.strategies.momentum import MomentumStrategy
from app.core.strategies.scalper import ScalperStrategy


_STRATEGY_CLASSES: dict[str, Callable[[], BaseStrategy]] = {
    "dip_hunter": DipHunterStrategy,
    "momentum": MomentumStrategy,
    "breakout": BreakoutStrategy,
    "scalper": ScalperStrategy,
}


@dataclass(frozen=True, slots=True)
class StrategyPreset:
    """Default strategy/risk overlays applied when a pipeline is created."""

    strategy: dict[str, float | int]
    risk: dict[str, float | int]
    budget_quote: float = 10_000.0


STRATEGY_PRESETS: dict[str, StrategyPreset] = {
    "dip_hunter": StrategyPreset(strategy={}, risk={}, budget_quote=10_000.0),
    "momentum": StrategyPreset(
        strategy={"watch_percent": 3.0, "entry_percent": 5.0},
        risk={"stop_loss_percent": 8.0, "max_open_positions": 5},
        budget_quote=10_000.0,
    ),
    "breakout": StrategyPreset(
        strategy={"watch_percent": 1.5, "entry_percent": 1.0},
        risk={"stop_loss_percent": 5.0, "max_open_positions": 5},
        budget_quote=10_000.0,
    ),
    "scalper": StrategyPreset(
        strategy={
            "watch_percent": 1.0,
            "entry_percent": 0.8,
            "max_position_hours": 4,
        },
        risk={
            "stop_loss_percent": 1.5,
            "trailing_activation_percent": 0.8,
            "trailing_percent": 0.5,
            "max_open_positions": 8,
            "max_daily_loss_percent": 10.0,
        },
        budget_quote=5_000.0,
    ),
}


def supported_strategy_names() -> list[str]:
    return sorted(_STRATEGY_CLASSES.keys())


def create_strategy(name: str) -> BaseStrategy:
    key = (name or "").strip().lower()
    if key not in _STRATEGY_CLASSES:
        raise ValueError(
            f"Unsupported strategy {name!r}. "
            f"Supported: {', '.join(supported_strategy_names())}"
        )
    return _STRATEGY_CLASSES[key]()


def apply_strategy_preset(
    base: AppSettings | None,
    strategy_name: str,
) -> AppSettings:
    """Deep-copies ``base`` (or a fresh AppSettings) and applies the preset."""
    config = copy.deepcopy(base) if base is not None else AppSettings()
    preset = STRATEGY_PRESETS.get(strategy_name.strip().lower())
    if preset is None:
        return config
    for key, value in preset.strategy.items():
        setattr(config.strategy, key, value)
    for key, value in preset.risk.items():
        setattr(config.risk, key, value)
    return config


def parse_enabled_strategies(raw: str | None = None) -> list[str]:
    """
    Reads ``STRATEGIES`` env (comma-separated) or returns ``[dip_hunter]``.
    """
    text = (raw if raw is not None else os.getenv("STRATEGIES") or "").strip()
    if not text:
        return ["dip_hunter"]
    names: list[str] = []
    for part in text.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name not in _STRATEGY_CLASSES:
            raise ValueError(
                f"Unknown strategy in STRATEGIES: {name!r}. "
                f"Supported: {', '.join(supported_strategy_names())}"
            )
        if name not in names:
            names.append(name)
    return names or ["dip_hunter"]


def pipeline_budget(strategy_name: str, default: float | None = None) -> float:
    env_key = f"STRATEGY_BUDGET_{strategy_name.strip().upper()}"
    raw = (os.getenv(env_key) or "").strip()
    if raw:
        return float(raw)
    preset = STRATEGY_PRESETS.get(strategy_name.strip().lower())
    if preset is not None:
        return float(preset.budget_quote)
    return float(default if default is not None else 10_000.0)
