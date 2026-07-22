"""
Sprint 6 -- Coin charts: assembles everything the UI needs to draw a
"TradingView-like" chart for one symbol -- its recent price candles plus
the Entry/Stop/Take-Profit/Trailing overlay levels for whichever trade
that symbol currently has (an open Position, or -- once it has closed --
the most recent Trade Journal entry).

Deliberately read-only and side-effect-free: this never places orders or
mutates Position/TradeJournal state, it only reads from
ExchangeManager/PositionManager/TradeJournal and shapes a ChartData for
the UI layer (app/ui/components/coin_chart.py) to render.
"""

import logging

from app.core.config.settings import AppSettings
from app.core.domain.chart import STATUS_CLOSED, STATUS_OPEN, ChartData
from app.core.domain.position import Position, PositionState
from app.core.domain.trade_journal import TradeJournalEntry
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType
from app.core.position_manager import PositionManager
from app.core.services.trade_journal import TradeJournal


logger = logging.getLogger(__name__)


class ChartService:
    def __init__(self) -> None:
        self._exchange_manager: ExchangeManager | None = None
        self._position_manager: PositionManager | None = None
        self._trade_journal: TradeJournal | None = None
        self._config: AppSettings | None = None

    def set_exchange_manager(self, exchange_manager: ExchangeManager) -> None:
        self._exchange_manager = exchange_manager

    def set_position_manager(self, position_manager: PositionManager) -> None:
        self._position_manager = position_manager

    def set_trade_journal(self, trade_journal: TradeJournal) -> None:
        self._trade_journal = trade_journal

    def set_config(self, config: AppSettings) -> None:
        self._config = config

    def build_chart_data(
        self,
        symbol: str,
        exchange_type: ExchangeType,
        *,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> ChartData:
        chart = ChartData(symbol=symbol, candles=self._fetch_candles(
            symbol,
            exchange_type,
            timeframe=timeframe,
            limit=limit,
        ))

        position = self._open_position(symbol, exchange_type)

        if position is not None:
            self._apply_open_position(chart, position)
            return chart

        journal_entry = (
            self._trade_journal.get_last_closed(symbol)
            if self._trade_journal is not None
            else None
        )

        if journal_entry is not None:
            self._apply_closed_trade(chart, journal_entry)

        return chart

    def _fetch_candles(
        self,
        symbol: str,
        exchange_type: ExchangeType,
        *,
        timeframe: str,
        limit: int,
    ):
        if self._exchange_manager is None:
            return []

        try:
            return self._exchange_manager.fetch_ohlcv(
                exchange_type,
                symbol,
                timeframe=timeframe,
                limit=limit,
            )
        except Exception:
            logger.exception(
                "ChartService: failed to fetch candles for %s", symbol
            )
            return []

    def _open_position(
        self,
        symbol: str,
        exchange_type: ExchangeType | None = None,
    ) -> Position | None:
        if self._position_manager is None:
            return None

        position = self._position_manager.get(
            symbol,
            exchange=exchange_type,
        )

        if position is None or position.state != PositionState.OPEN:
            return None

        return position

    def _apply_open_position(self, chart: ChartData, position: Position) -> None:
        chart.status = STATUS_OPEN
        chart.entry_price = position.entry_price
        chart.entry_time = position.opened_at
        chart.stop_price = position.stop_price
        chart.stop_stage = position.stop_stage
        chart.trailing_reference_price = position.highest_price
        chart.take_profit_price = self._take_profit_price(position.entry_price)

    def _apply_closed_trade(
        self,
        chart: ChartData,
        entry: TradeJournalEntry,
    ) -> None:
        chart.status = STATUS_CLOSED
        chart.entry_price = entry.entry_price
        chart.entry_time = entry.entry_time
        chart.exit_price = entry.exit_price
        chart.exit_time = entry.exit_time
        chart.exit_reason = entry.exit_reason
        chart.take_profit_price = self._take_profit_price(entry.entry_price)

    def _take_profit_price(self, entry_price: float | None) -> float | None:
        if entry_price is None or self._config is None:
            return None

        activation_percent = self._config.risk.trailing_activation_percent

        return entry_price * (1 + activation_percent / 100)
