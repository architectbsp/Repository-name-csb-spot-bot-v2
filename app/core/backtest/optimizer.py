"""
Parameter optimizer -- Grid Search or Genetic Algorithm over BacktestEngine,
scoring trials by Profit Factor.
"""

from __future__ import annotations

import copy
import itertools
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.backtest.engine import BacktestEngine, BacktestResult
from app.core.config.settings import AppSettings
from app.core.domain.candle import Candle


logger = logging.getLogger(__name__)

OptimizerMethod = Literal["grid", "genetic"]


@dataclass(frozen=True, slots=True)
class ParamRange:
    """
    Search range for a dotted setting path, e.g.
    ``risk.stop_loss_percent`` or ``strategy.watch_percent``.
    """

    path: str
    start: float
    stop: float
    step: float | None = None  # required for grid; optional for GA


@dataclass(slots=True)
class OptimizationTrial:
    params: dict[str, float]
    profit_factor: float
    total_trades: int
    total_pnl: float
    fitness: float
    result: BacktestResult | None = None


@dataclass(slots=True)
class OptimizationResult:
    method: OptimizerMethod
    best: OptimizationTrial
    trials: list[OptimizationTrial] = field(default_factory=list)

    @property
    def best_params(self) -> dict[str, float]:
        return dict(self.best.params)


def _resolve_attr(root: Any, path: str) -> tuple[Any, str]:
    parts = path.split(".")
    if len(parts) < 2:
        raise ValueError(f"Param path must be dotted (section.field): {path!r}")
    obj = root
    for part in parts[:-1]:
        obj = getattr(obj, part)
    return obj, parts[-1]


def apply_params(config: AppSettings, params: dict[str, float]) -> AppSettings:
    cfg = copy.deepcopy(config)
    for path, value in params.items():
        obj, attr = _resolve_attr(cfg, path)
        current = getattr(obj, attr)
        if isinstance(current, int) and not isinstance(current, bool):
            setattr(obj, attr, int(round(value)))
        else:
            setattr(obj, attr, float(value))
    return cfg


def profit_factor_fitness(result: BacktestResult) -> float:
    """
    Higher is better. ``None`` → 0; ``+inf`` (wins, no losses) capped.
    Tiny trade-count tie-breaker prefers more evidence.
    """
    pf = result.report.profit_factor
    if pf is None:
        score = 0.0
    elif pf == float("inf"):
        score = 1_000_000.0
    else:
        score = float(pf)
    return score + (result.report.total_trades * 1e-6)


def _grid_values(spec: ParamRange) -> list[float]:
    if spec.step is None or spec.step <= 0:
        raise ValueError(f"Grid search requires positive step for {spec.path}")
    values: list[float] = []
    cursor = float(spec.start)
    # Inclusive stop with float-safe epsilon.
    while cursor <= spec.stop + 1e-12:
        values.append(round(cursor, 10))
        cursor += spec.step
    if not values:
        raise ValueError(f"Empty grid for {spec.path}")
    return values


class ParameterOptimizer:
    """
    Runs many BacktestEngine trials and returns the params with the
    highest Profit Factor fitness.
    """

    def __init__(
        self,
        candles: list[Candle],
        *,
        base_config: AppSettings | None = None,
        symbol: str = "BTC/USDT",
        initial_balance: float = 10_000.0,
        strategy_name: str = "dip_hunter",
        fee_rate: float = 0.0,
    ) -> None:
        self._candles = candles
        self._base_config = base_config or AppSettings()
        self._symbol = symbol
        self._initial_balance = initial_balance
        self._strategy_name = strategy_name
        self._fee_rate = fee_rate

    def optimize(
        self,
        space: list[ParamRange],
        *,
        method: OptimizerMethod = "grid",
        # Genetic controls
        population_size: int = 12,
        generations: int = 8,
        mutation_rate: float = 0.25,
        elite_count: int = 2,
        seed: int | None = 42,
    ) -> OptimizationResult:
        if not space:
            raise ValueError("Parameter space is empty")

        if method == "grid":
            trials = self._grid_search(space)
        elif method == "genetic":
            trials = self._genetic_search(
                space,
                population_size=population_size,
                generations=generations,
                mutation_rate=mutation_rate,
                elite_count=elite_count,
                seed=seed,
            )
        else:
            raise ValueError(f"Unknown optimizer method: {method!r}")

        if not trials:
            raise RuntimeError("Optimizer produced no trials")

        best = max(trials, key=lambda t: t.fitness)
        logger.info(
            "[OPTIMIZER] method=%s trials=%d best_pf=%.4f params=%s",
            method,
            len(trials),
            best.profit_factor,
            best.params,
        )
        return OptimizationResult(method=method, best=best, trials=trials)

    def _evaluate(self, params: dict[str, float]) -> OptimizationTrial:
        config = apply_params(self._base_config, params)
        # Liquidity-only sizing keeps trials comparable when ATR history
        # is short at the start of a series.
        config.risk.position_sizing_mode = 0
        config.strategy.trading_hours_enabled = 0

        result = BacktestEngine(
            self._candles,
            symbol=self._symbol,
            config=config,
            initial_balance=self._initial_balance,
            fee_rate=self._fee_rate,
            strategy_name=self._strategy_name,
        ).run()

        pf = result.report.profit_factor
        pf_score = 0.0 if pf is None else (
            1_000_000.0 if pf == float("inf") else float(pf)
        )
        fitness = profit_factor_fitness(result)
        return OptimizationTrial(
            params=dict(params),
            profit_factor=pf_score,
            total_trades=result.report.total_trades,
            total_pnl=result.report.total_pnl,
            fitness=fitness,
            result=result,
        )

    def _grid_search(self, space: list[ParamRange]) -> list[OptimizationTrial]:
        axes = [_grid_values(spec) for spec in space]
        paths = [spec.path for spec in space]
        trials: list[OptimizationTrial] = []
        for combo in itertools.product(*axes):
            params = {path: value for path, value in zip(paths, combo, strict=True)}
            trials.append(self._evaluate(params))
        return trials

    def _genetic_search(
        self,
        space: list[ParamRange],
        *,
        population_size: int,
        generations: int,
        mutation_rate: float,
        elite_count: int,
        seed: int | None,
    ) -> list[OptimizationTrial]:
        rng = random.Random(seed)
        population = [
            self._random_individual(space, rng) for _ in range(population_size)
        ]
        evaluated = [self._evaluate(ind) for ind in population]
        all_trials = list(evaluated)

        for gen in range(generations):
            evaluated.sort(key=lambda t: t.fitness, reverse=True)
            elites = evaluated[: max(1, elite_count)]
            next_pop = [dict(e.params) for e in elites]

            while len(next_pop) < population_size:
                parent_a = self._tournament(evaluated, rng)
                parent_b = self._tournament(evaluated, rng)
                child = self._crossover(parent_a.params, parent_b.params, space, rng)
                if rng.random() < mutation_rate:
                    child = self._mutate(child, space, rng)
                next_pop.append(child)

            evaluated = [self._evaluate(ind) for ind in next_pop]
            all_trials.extend(evaluated)
            logger.debug(
                "[OPTIMIZER:GA] gen=%d best_fitness=%.6f",
                gen + 1,
                max(t.fitness for t in evaluated),
            )

        return all_trials

    def _random_individual(
        self,
        space: list[ParamRange],
        rng: random.Random,
    ) -> dict[str, float]:
        params: dict[str, float] = {}
        for spec in space:
            if spec.step and spec.step > 0:
                choices = _grid_values(spec)
                params[spec.path] = rng.choice(choices)
            else:
                params[spec.path] = rng.uniform(spec.start, spec.stop)
        return params

    @staticmethod
    def _tournament(
        trials: list[OptimizationTrial],
        rng: random.Random,
        k: int = 3,
    ) -> OptimizationTrial:
        sample = rng.sample(trials, min(k, len(trials)))
        return max(sample, key=lambda t: t.fitness)

    @staticmethod
    def _crossover(
        a: dict[str, float],
        b: dict[str, float],
        space: list[ParamRange],
        rng: random.Random,
    ) -> dict[str, float]:
        child: dict[str, float] = {}
        for spec in space:
            child[spec.path] = a[spec.path] if rng.random() < 0.5 else b[spec.path]
        return child

    @staticmethod
    def _mutate(
        individual: dict[str, float],
        space: list[ParamRange],
        rng: random.Random,
    ) -> dict[str, float]:
        mutated = dict(individual)
        spec = rng.choice(space)
        if spec.step and spec.step > 0:
            mutated[spec.path] = rng.choice(_grid_values(spec))
        else:
            mutated[spec.path] = rng.uniform(spec.start, spec.stop)
        return mutated
