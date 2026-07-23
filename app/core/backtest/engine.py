"""
BacktestEngine -- replays OHLCV through Strategy + RiskManager with paper
execution and returns a PerformanceReport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC

from app.core.config.settings import AppSettings
from app.core.domain.candle import Candle
from app.core.domain.performance import PerformanceReport
from app.core.exchange.adapter import PaperExchangeAdapter
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.core.market_data.models import NormalizedTicker
from app.core.persistence.service import PersistenceService
from app.core.position_manager import PositionManager
from app.core.risk_manager import RiskManager
from app.core.services.analytics_service import AnalyticsService
from app.core.services.order_validator import OrderValidator
from app.core.services.trade_journal import TradeJournal
from app.core.strategies.base import BaseStrategy
from app.core.strategies.factory import create_strategy
from app.core.watch_list import WatchList


logger = logging.getLogger(__name__)

# Bars used to synthesize change_24h when timeframe is unknown.
_DEFAULT_CHANGE_LOOKBACK = 24


@dataclass(slots=True)
class BacktestResult:
    report: PerformanceReport
    candles_processed: int
    symbol: str
    exchange: ExchangeType
    final_quote_balance: float
    initial_quote_balance: float

    @property
    def equity_pnl(self) -> float:
        return self.final_quote_balance - self.initial_quote_balance


class BacktestEngine:
    """
    Runs the live Strategy + RiskManager stack over historical candles.

    Execution is mocked via ``PaperExchangeAdapter`` (no live orders).
    Each candle updates the mark price, synthesizes a ticker (including
    ``change_24h`` from a lookback close), then feeds WatchList / Strategy
    and RiskManager stop logic -- the same path used in production ticks.
    """

    def __init__(
        self,
        candles: list[Candle],
        *,
        symbol: str = "BTC/USDT",
        exchange_type: ExchangeType = ExchangeType.BINANCE,
        config: AppSettings | None = None,
        initial_balance: float = 10_000.0,
        quote: str = "USDT",
        fee_rate: float = 0.001,
        change_lookback_bars: int = _DEFAULT_CHANGE_LOOKBACK,
        volume_24h: float | None = None,
        strategy_name: str = "dip_hunter",
    ) -> None:
        if not candles:
            raise ValueError("Backtest requires at least one candle")

        self._candles = sorted(candles, key=lambda c: c.timestamp)
        self._symbol = symbol
        self._exchange_type = exchange_type
        self._config = config or AppSettings()
        self._initial_balance = float(initial_balance)
        self._quote = quote
        self._fee_rate = fee_rate
        self._change_lookback = max(1, int(change_lookback_bars))
        self._strategy_name = strategy_name
        # Default liquidity large enough not to starve sizing in tests.
        self._volume_24h = (
            float(volume_24h)
            if volume_24h is not None
            else max(float(self._config.strategy.min_volume_usd) * 10, 1_000_000.0)
        )

        self._paper: PaperExchangeAdapter | None = None
        self._watch_list: WatchList | None = None
        self._strategy: BaseStrategy | None = None
        self._risk_manager: RiskManager | None = None
        self._analytics: AnalyticsService | None = None
        self._exchange_manager: ExchangeManager | None = None

    def run(self) -> BacktestResult:
        self._wire()
        assert self._paper is not None
        assert self._watch_list is not None
        assert self._risk_manager is not None
        assert self._analytics is not None

        closes: list[float] = []

        for index, candle in enumerate(self._candles):
            # Drive open → high → low → close so stops can fire intra-bar
            # on the adverse excursion before the bar settles.
            path = (candle.open, candle.high, candle.low, candle.close)

            for price in path:
                self._paper.set_mark_price(self._symbol, price)
                change_24h = self._change_24h(closes, price)
                ticker = NormalizedTicker(
                    exchange=self._exchange_type,
                    symbol=self._symbol,
                    last_price=price,
                    volume_24h=self._volume_24h,
                    change_24h=change_24h,
                    timestamp=candle.timestamp,
                    raw_last_price=f"{price:.8f}",
                )

                if index == 0 and price == candle.open:
                    self._watch_list.handle_scan_result([ticker])
                else:
                    self._watch_list.handle_price_update(ticker)

                self._risk_manager.on_price_tick(ticker)

            closes.append(candle.close)
            # Keep ATR/vol sizing fed with history seen so far.
            self._paper.seed_ohlcv(self._symbol, self._candles[: index + 1])

        report = self._analytics.generate_report()
        final_balance = self._paper.fetch_quote_balance(self._quote)

        return BacktestResult(
            report=report,
            candles_processed=len(self._candles),
            symbol=self._symbol,
            exchange=self._exchange_type,
            final_quote_balance=final_balance,
            initial_quote_balance=self._initial_balance,
        )

    def _wire(self) -> None:
        paper = PaperExchangeAdapter(
            live=None,
            exchange_type=self._exchange_type,
            initial_quote=self._initial_balance,
            quote=self._quote,
            fee_rate=self._fee_rate,
        )
        paper.seed_ohlcv(self._symbol, self._candles)
        paper.connect()

        registry = ExchangeRegistry()
        registry.register(self._exchange_type, paper)
        exchange_manager = ExchangeManager(registry)

        persistence = PersistenceService.from_url("sqlite:///:memory:")
        position_manager = PositionManager()
        position_manager.set_repository(persistence.position_repository())

        trade_journal = TradeJournal()
        trade_journal.set_repository(persistence.trade_journal_repository())

        order_validator = OrderValidator(exchange_manager)

        risk_manager = RiskManager()
        risk_manager.set_exchange(exchange_manager)
        risk_manager.set_exchange_manager(exchange_manager)
        risk_manager.set_position_manager(position_manager)
        risk_manager.set_order_validator(order_validator)
        risk_manager.set_trade_journal(trade_journal)
        risk_manager.set_config(self._config)
        risk_manager.initialize()
        risk_manager.start()

        strategy = create_strategy(self._strategy_name)
        strategy.set_risk_manager(risk_manager)
        strategy.set_position_manager(position_manager)
        strategy.set_trade_journal(trade_journal)
        strategy.set_config(self._config)
        strategy.initialize()
        strategy.start()

        watch_list = WatchList()
        watch_list.set_exchange(exchange_manager)
        watch_list.set_strategy(strategy)
        watch_list.set_config(self._config)

        analytics = AnalyticsService()
        analytics.set_trade_journal(trade_journal)

        self._paper = paper
        self._watch_list = watch_list
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._analytics = analytics
        self._exchange_manager = exchange_manager

        logger.info(
            "[BACKTEST] Wired paper engine for %s on %s (%d candles, balance=%.2f)",
            self._symbol,
            self._exchange_type.name,
            len(self._candles),
            self._initial_balance,
        )

    def _change_24h(self, closes: list[float], price: float) -> float:
        if len(closes) <= 1:
            # Warm-up: use price vs first open so Path A/B can still fire
            # on short fixture series.
            ref = self._candles[0].open
        else:
            lookback_index = max(0, len(closes) - 1 - self._change_lookback)
            ref = closes[lookback_index]
        if ref <= 0:
            return 0.0
        return ((price - ref) / ref) * 100.0


def format_report(result: BacktestResult) -> str:
    """Human-readable summary for CLI / logs."""
    r = result.report
    lines = [
        f"Backtest {result.symbol} ({result.exchange.name})",
        f"Candles: {result.candles_processed}",
        f"Generated: {r.generated_at.astimezone(UTC).isoformat()}",
        f"Trades: {r.total_trades} (W {r.winning_trades} / L {r.losing_trades} / BE {r.breakeven_trades})",
        f"Win rate: {r.win_rate_percent:.2f}%",
        f"Total PnL: {r.total_pnl:.4f}",
        f"Expectancy: {r.expectancy:.4f}",
        f"Profit factor: {r.profit_factor}",
        f"Sharpe: {r.sharpe_ratio}",
        f"Max DD: {r.max_drawdown:.4f} ({r.max_drawdown_percent:.2f}%)",
        f"Wallet: {result.initial_quote_balance:.2f} → {result.final_quote_balance:.2f} "
        f"(Δ {result.equity_pnl:.4f})",
    ]
    return "\n".join(lines)
