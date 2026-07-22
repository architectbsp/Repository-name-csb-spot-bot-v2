"""
Sprint 12 -- Live Dashboard snapshot builder.

Read-only aggregator: pulls open positions, watch/cooldown state, trade
journal, daily PnL, quote balance and recent logs into one
DashboardSnapshot the UI can render without knowing about any core
module. Also keeps a last-ticker cache fed by `ticker.updated` (and
seeded from MarketScanner's last scan) so "current price" / unrealized
PnL never require a REST call on every UI poll.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from app.core.config.settings import AppSettings
from app.core.domain.dashboard import (
    CoinRow,
    CooldownRow,
    DashboardSnapshot,
    OpenPositionRow,
    Report24h,
    TradeHistoryRow,
    WatchRow,
)
from app.core.domain.trade_journal import STATUS_CLOSED
from app.core.exchange.market_key import exchange_name, market_key
from app.core.exchange.models import ConnectionStatus, ExchangeType
from app.core.market_data.models import NormalizedTicker
from app.core.services.memory_log import get_memory_log_handler
from app.core.watch_list import WatchState


logger = logging.getLogger(__name__)

_ACTIVE_WATCH_STATES = {
    WatchState.WATCH_FALLING,
    WatchState.WATCH_RISING,
    WatchState.BUY_PENDING,
}

_POSITION_STATES = {
    WatchState.POSITION_OPEN,
    WatchState.BREAK_EVEN,
    WatchState.TRAILING_ACTIVE,
}

_COIN_TABLE_STATES = _ACTIVE_WATCH_STATES | _POSITION_STATES | {
    WatchState.COOLDOWN,
    WatchState.IDLE,
}


class DashboardService:
    def __init__(self) -> None:
        self._exchange_manager = None
        self._position_manager = None
        self._watch_list = None
        self._trade_journal = None
        self._risk_manager = None
        self._market_scanner = None
        self._analytics_service = None
        self._config: AppSettings | None = None
        self._bot_running_fn = lambda: False

        self._tickers: dict[str, NormalizedTicker] = {}
        self._ticker_lock = threading.Lock()
        self._memory_log = get_memory_log_handler()

    # ---- wiring ---------------------------------------------------------

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_watch_list(self, watch_list) -> None:
        self._watch_list = watch_list

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def set_risk_manager(self, risk_manager) -> None:
        self._risk_manager = risk_manager

    def set_market_scanner(self, market_scanner) -> None:
        self._market_scanner = market_scanner

    def set_analytics_service(self, analytics_service) -> None:
        self._analytics_service = analytics_service

    def set_config(self, config: AppSettings) -> None:
        self._config = config

    def set_bot_running_fn(self, fn) -> None:
        self._bot_running_fn = fn

    def on_ticker_updated(self, ticker: NormalizedTicker) -> None:
        """EventBus handler for `ticker.updated` -- caches the latest
        price per (exchange, symbol) so the UI poll never hits REST."""
        if ticker is None:
            return
        with self._ticker_lock:
            self._tickers[_ticker_cache_key(ticker)] = ticker

    def seed_tickers_from_scan(self) -> None:
        """Pull MarketScanner's last scan result into the ticker cache
        (covers symbols that aren't on the WebSocket watch yet)."""
        if self._market_scanner is None:
            return
        result = self._market_scanner.last_scan_result()
        if not result:
            return
        with self._ticker_lock:
            for ticker in result:
                self._tickers[_ticker_cache_key(ticker)] = ticker

    # ---- snapshot -------------------------------------------------------

    def build_snapshot(self) -> DashboardSnapshot:
        now = datetime.now(UTC)
        self.seed_tickers_from_scan()

        name, enabled, api_connected, testnet = self._exchange_status()
        balance = self._quote_balance()
        daily_pnl, daily_pct, day_start = self._daily_pnl()

        open_positions = self._open_position_rows()
        watch_rows = self._watch_rows()
        cooldown_rows = self._cooldown_rows(now)
        coin_rows = self._coin_rows()
        history_rows, report = self._history_and_report_24h(now)
        performance = (
            self._analytics_service.generate_report()
            if self._analytics_service is not None
            else None
        )

        return DashboardSnapshot(
            generated_at=now,
            bot_running=bool(self._bot_running_fn()),
            exchange_name=name,
            enabled_exchanges=enabled,
            testnet=testnet,
            api_connected=api_connected,
            quote_balance=balance,
            available_balance=balance,
            daily_realized_pnl=daily_pnl,
            daily_pnl_percent=daily_pct,
            day_start_balance=day_start,
            open_position_count=len(open_positions),
            active_signal_count=len(watch_rows),
            coins=coin_rows,
            open_positions=open_positions,
            watch_list=watch_rows,
            cooldowns=cooldown_rows,
            trade_history=history_rows,
            report_24h=report,
            performance=performance,
            logs=self._memory_log.recent(limit=30),
        )

    # ---- private helpers ------------------------------------------------

    def _exchange_status(self) -> tuple[str, list[str], bool, bool]:
        if self._exchange_manager is None:
            return "-", [], False, bool(
                self._config.exchange.testnet if self._config else False
            )

        testnet = bool(
            self._config.exchange.testnet if self._config is not None else False
        )

        enabled_names: list[str] = []
        connected = False
        try:
            for exchange in self._exchange_manager.enabled():
                et = exchange.state.exchange
                enabled_names.append(
                    et.name if isinstance(et, ExchangeType) else str(et)
                )
                if exchange.state.status == ConnectionStatus.CONNECTED:
                    connected = True
        except Exception:
            return "-", [], False, testnet

        if not enabled_names:
            return "-", [], False, testnet

        return ",".join(enabled_names), enabled_names, connected, testnet

    def _quote_balance(self) -> float | None:
        """Sprint 18: sum free quote balances across every enabled venue."""
        if self._exchange_manager is None:
            return None
        try:
            exchange_types = self._exchange_manager.enabled_exchange_types()
        except Exception:
            logger.debug("Dashboard: quote balance unavailable", exc_info=True)
            return None

        total = 0.0
        any_ok = False
        for exchange_type in exchange_types:
            try:
                total += float(
                    self._exchange_manager.get_quote_balance(exchange_type)
                )
                any_ok = True
            except Exception:
                logger.debug(
                    "Dashboard: quote balance unavailable for %s",
                    exchange_type,
                    exc_info=True,
                )
        return total if any_ok else None

    def _daily_pnl(self) -> tuple[float | None, float | None, float | None]:
        if self._risk_manager is None:
            return None, None, None

        day_start = self._risk_manager.day_start_balance()
        realized = self._risk_manager.realized_pnl_today()

        if day_start is None or day_start <= 0:
            return realized, None, day_start

        return realized, (realized / day_start) * 100.0, day_start

    def _ticker(self, symbol: str, exchange=None) -> NormalizedTicker | None:
        keys = []
        if exchange is not None:
            keys.append(market_key(exchange, symbol))
            keys.append(market_key(exchange, _alt_symbol(symbol)))
        keys.append(symbol)
        keys.append(_alt_symbol(symbol))

        with self._ticker_lock:
            for key in keys:
                ticker = self._tickers.get(key)
                if ticker is not None:
                    return ticker

            # Legacy / missing exchange on Position or WatchList: accept a
            # unique cached ticker for this symbol across venues.
            alt = _alt_symbol(symbol)
            matches = [
                ticker
                for key, ticker in self._tickers.items()
                if ticker.symbol in (symbol, alt)
                or key.endswith(f":{symbol}")
                or key.endswith(f":{alt}")
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    def _open_position_rows(self) -> list[OpenPositionRow]:
        if self._position_manager is None:
            return []

        rows: list[OpenPositionRow] = []
        for position in self._position_manager.get_open_positions():
            venue = _venue_label(position.exchange)
            ticker = self._ticker(position.symbol, position.exchange)
            current = ticker.last_price if ticker is not None else None
            pnl_percent = None
            if current is not None and position.entry_price:
                pnl_percent = (
                    (current - position.entry_price) / position.entry_price
                ) * 100.0

            rows.append(
                OpenPositionRow(
                    symbol=position.symbol,
                    entry_price=position.entry_price,
                    current_price=current,
                    pnl_percent=pnl_percent,
                    stop_stage=position.stop_stage,
                    quantity=position.quantity,
                    exchange=venue,
                )
            )
        return rows

    def _watch_rows(self) -> list[WatchRow]:
        if self._watch_list is None:
            return []

        rows: list[WatchRow] = []
        for key, coin in self._watch_list.list_by_states(_ACTIVE_WATCH_STATES):
            symbol, venue = _coin_identity(key, coin)
            state = coin["state"]
            ticker = self._ticker(symbol, coin.get("exchange") or venue)
            change = ticker.change_24h if ticker is not None else 0.0
            direction = (
                "DIP" if state == WatchState.WATCH_FALLING else "RISE"
            )
            rows.append(
                WatchRow(
                    symbol=symbol,
                    direction=direction,
                    change_display=_format_signed_percent(change),
                    status=_watch_status_label(state),
                    exchange=venue,
                )
            )
        return rows

    def _cooldown_rows(self, now: datetime) -> list[CooldownRow]:
        if self._watch_list is None:
            return []

        rows: list[CooldownRow] = []
        for key, coin in self._watch_list.list_by_states({WatchState.COOLDOWN}):
            symbol, venue = _coin_identity(key, coin)
            remaining = self._watch_list.remaining_cooldown(key, now)
            rows.append(
                CooldownRow(
                    symbol=symbol,
                    cooldown_until=coin.get("cooldown_until"),
                    remaining_seconds=(
                        remaining.total_seconds() if remaining is not None else None
                    ),
                    exchange=venue,
                )
            )
        return rows

    def _coin_rows(self) -> list[CoinRow]:
        """Coin table: watched coins first, then any open-position symbols
        not already on the watch list, enriched with last-known ticker."""
        if self._watch_list is None:
            return []

        rows: list[CoinRow] = []
        seen: set[str] = set()

        for key, coin in self._watch_list.list_by_states(_COIN_TABLE_STATES):
            symbol, venue = _coin_identity(key, coin)
            seen.add(key if ":" in key else market_key(venue, symbol))
            state = coin["state"]
            ticker = self._ticker(symbol, coin.get("exchange") or venue)
            rows.append(
                CoinRow(
                    symbol=symbol,
                    price_display=_price_display(ticker),
                    change_24h_percent=(
                        ticker.change_24h if ticker is not None else 0.0
                    ),
                    volume_24h=ticker.volume_24h if ticker is not None else 0.0,
                    signal=_signal_for_state(state),
                    status=str(state),
                    exchange=venue,
                )
            )

        if self._position_manager is not None:
            for position in self._position_manager.get_open_positions():
                venue = _venue_label(position.exchange)
                pos_key = market_key(position.exchange, position.symbol)
                if pos_key in seen or position.symbol in seen:
                    continue
                ticker = self._ticker(position.symbol, position.exchange)
                rows.append(
                    CoinRow(
                        symbol=position.symbol,
                        price_display=_price_display(ticker),
                        change_24h_percent=(
                            ticker.change_24h if ticker is not None else 0.0
                        ),
                        volume_24h=(
                            ticker.volume_24h if ticker is not None else 0.0
                        ),
                        signal="HOLD",
                        status="POSITION_OPEN",
                        exchange=venue,
                    )
                )

        return rows

    def _history_and_report_24h(
        self,
        now: datetime,
    ) -> tuple[list[TradeHistoryRow], Report24h]:
        history: list[TradeHistoryRow] = []
        report = Report24h()

        if self._trade_journal is None:
            return history, report

        cutoff = now - timedelta(hours=24)
        closed = [
            entry
            for entry in self._trade_journal.list_all()
            if entry.status == STATUS_CLOSED
        ]

        # Newest first for the history panel.
        closed_sorted = sorted(
            closed,
            key=lambda e: e.exit_time or e.entry_time,
            reverse=True,
        )

        for entry in closed_sorted[:20]:
            history.append(
                TradeHistoryRow(
                    symbol=entry.symbol,
                    pnl_percent=entry.pnl_percent,
                    result=_result_label(entry.pnl, entry.exit_reason),
                    exit_reason=entry.exit_reason,
                    exchange=_venue_label(entry.exchange),
                )
            )

        recent = [
            entry
            for entry in closed
            if entry.exit_time is not None
            and _as_utc(entry.exit_time) >= cutoff
        ]
        report.total_trades = len(recent)
        for entry in recent:
            pnl = entry.pnl or 0.0
            if pnl > 0:
                report.winning_trades += 1
                report.gross_profit += pnl
            elif pnl < 0:
                report.losing_trades += 1
                report.gross_loss += abs(pnl)
            report.net_pnl += pnl

        return history, report


def _as_utc(value: datetime) -> datetime:
    """Normalize possibly-naive datetimes (SQLite DateTime columns) to
    aware UTC so the 24h report window comparison never TypeErrors."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _alt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol.replace("/", "")
    if symbol.endswith("USDT") and len(symbol) > 4:
        return f"{symbol[:-4]}/USDT"
    return symbol


def _ticker_cache_key(ticker: NormalizedTicker) -> str:
    return market_key(getattr(ticker, "exchange", None), ticker.symbol)


def _venue_label(exchange) -> str | None:
    if exchange is None:
        return None
    name = exchange_name(exchange)
    return None if name == "UNKNOWN" else name


def _coin_identity(key: str, coin: dict) -> tuple[str, str | None]:
    symbol = coin.get("symbol") or key
    venue = _venue_label(coin.get("exchange"))
    if venue is None and ":" in key:
        venue = key.split(":", 1)[0]
        if not coin.get("symbol"):
            symbol = key.split(":", 1)[1]
    return symbol, venue


def _price_display(ticker: NormalizedTicker | None) -> str:
    if ticker is None:
        return "-"
    # docs/BUSINESS_RULES.md §9: prefer the untouched exchange string.
    if ticker.raw_last_price:
        return ticker.raw_last_price
    return f"{ticker.last_price:g}"


def _format_signed_percent(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _signal_for_state(state: WatchState) -> str:
    if state == WatchState.BUY_PENDING:
        return "BUY"
    if state in _POSITION_STATES:
        return "HOLD"
    return "WAIT"


def _watch_status_label(state: WatchState) -> str:
    return {
        WatchState.WATCH_FALLING: "Dip Takip",
        WatchState.WATCH_RISING: "Yükseliş İzleniyor",
        WatchState.BUY_PENDING: "Alım Bekleniyor",
    }.get(state, str(state))


def _result_label(pnl: float | None, exit_reason: str | None) -> str:
    if pnl is not None and pnl > 0:
        return "KÂR"
    if exit_reason and "STOP" in exit_reason.upper():
        return "STOP"
    if pnl is not None and pnl < 0:
        return "STOP"
    return "KAPANDI"
