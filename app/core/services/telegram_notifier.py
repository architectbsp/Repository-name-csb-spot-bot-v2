"""
Sprint 11 -- Telegram notifier.

Subscribes to BotEngine EventBus topics and formats operator-facing
alerts (BUY / SELL / STOP / ERROR / API disconnect / internet
disconnect / daily & weekly summaries). Never places orders or mutates
trading state; send failures are swallowed by TelegramClient.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.config.settings import AppSettings, TelegramSettings
from app.core.domain.trade_journal import STATUS_CLOSED
from app.core.exchange.models import ConnectionStatus
from app.core.scheduler.job import Job
from app.core.services.telegram_client import TelegramClient


logger = logging.getLogger(__name__)

_STOP_REASONS = frozenset(
    {
        "STOP_LOSS",
        "HARD_STOP",  # legacy alias
        "BREAK_EVEN_STOP",
        "TRAILING_STOP",
    }
)

_TICK_JOB = "telegram_notifier_tick"
_TICK_INTERVAL_SECONDS = 30


class TelegramNotifier:
    def __init__(
        self,
        client: TelegramClient | None = None,
    ) -> None:
        self._client = client
        self._config: AppSettings | None = None
        self._event_bus = None
        self._scheduler = None
        self._exchange_manager = None
        self._trade_journal = None
        self._risk_manager = None
        self._position_manager = None
        self._initialized = False

        self._internet_ok: bool | None = None
        self._api_ok: dict[str, bool] = {}
        self._last_daily_key: str | None = None
        self._last_weekly_key: str | None = None

    # ---- wiring ---------------------------------------------------------

    def set_client(self, client: TelegramClient) -> None:
        self._client = client

    def set_config(self, config: AppSettings) -> None:
        self._config = config

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def set_risk_manager(self, risk_manager) -> None:
        self._risk_manager = risk_manager

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def _settings(self) -> TelegramSettings | None:
        if self._config is None:
            return None
        return self._config.telegram

    def is_enabled(self) -> bool:
        settings = self._settings()
        if settings is None or not settings.enabled:
            return False
        if self._client is None or not self._client.configured:
            return False
        return True

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        if self._event_bus is not None:
            self._event_bus.subscribe("position.opened", self.on_position_opened)
            self._event_bus.subscribe("position.closed", self.on_position_closed)
            self._event_bus.subscribe(
                "position.partial_exit", self.on_partial_exit
            )
            self._event_bus.subscribe(
                "order.needs_manual_review", self.on_execution_error
            )
            self._event_bus.subscribe(
                "risk.daily_loss_limit", self.on_daily_loss_limit
            )
            self._event_bus.subscribe(
                "exchange.disconnected", self.on_exchange_disconnected
            )
            self._event_bus.subscribe(
                "exchange.connected", self.on_exchange_connected
            )

        if self._scheduler is not None and not self._scheduler.has_job(_TICK_JOB):
            interval = (
                self._settings().connectivity_probe_seconds
                if self._settings() is not None
                else _TICK_INTERVAL_SECONDS
            )
            job = Job(
                name=_TICK_JOB,
                interval=max(15, int(interval)),
                callback=self.tick,
            )
            self._scheduler.register(job)
            self._scheduler.schedule(job)

    def shutdown(self) -> None:
        self._initialized = False
        if self._scheduler is not None and self._scheduler.has_job(_TICK_JOB):
            self._scheduler.unregister(_TICK_JOB)
        if self._client is not None:
            self._client.close()

    def start(self) -> None:
        if self.is_enabled():
            self._send(
                "🤖 CSB Spot Bot Telegram notifier online "
                f"({datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC)"
            )

    def stop(self) -> None:
        if self.is_enabled():
            self._send("⏹ CSB Spot Bot Telegram notifier stopped")

    # ---- event handlers -------------------------------------------------

    def on_position_opened(self, event: dict) -> None:
        symbol = event.get("symbol", "?")
        exchange = event.get("exchange", "")
        price = event.get("entry_price")
        qty = event.get("quantity")
        stop = event.get("stop_price")
        venue = f" [{exchange}]" if exchange else ""
        self._send(
            f"🟢 BUY{venue}\n"
            f"Symbol: {symbol}\n"
            f"Entry: {_fmt(price)}\n"
            f"Qty: {_fmt(qty)}\n"
            f"Stop: {_fmt(stop)}"
        )

    def on_position_closed(self, event: dict) -> None:
        symbol = event.get("symbol", "?")
        exchange = event.get("exchange", "")
        reason = str(event.get("reason") or "")
        price = event.get("price") or event.get("exit_price")
        position = event.get("position")
        pnl = getattr(position, "pnl", None) if position is not None else event.get("pnl")
        pnl_pct = (
            getattr(position, "pnl_percent", None)
            if position is not None
            else event.get("pnl_percent")
        )
        venue = f" [{exchange}]" if exchange else ""

        if reason in _STOP_REASONS:
            title = f"🛑 STOP ({reason}){venue}"
        else:
            title = f"🔴 SELL ({reason or 'CLOSED'}){venue}"

        self._send(
            f"{title}\n"
            f"Symbol: {symbol}\n"
            f"Exit: {_fmt(price)}\n"
            f"PnL: {_fmt(pnl)} ({_fmt(pnl_pct)}%)"
        )

    def on_partial_exit(self, event: dict) -> None:
        symbol = event.get("symbol", "?")
        self._send(
            f"🟠 PARTIAL SELL\n"
            f"Symbol: {symbol}\n"
            f"Qty: {_fmt(event.get('quantity'))}\n"
            f"Exit: {_fmt(event.get('exit_price'))}\n"
            f"Realized: {_fmt(event.get('realized_pnl'))}"
        )

    def on_execution_error(self, event: dict) -> None:
        self._send(
            "⚠️ ERROR — manual review required\n"
            f"Symbol: {event.get('symbol', '?')}\n"
            f"Side: {event.get('side', '?')}\n"
            f"Outcome: {event.get('outcome', '?')}\n"
            f"Detail: {event.get('error', '-')}"
        )

    def on_daily_loss_limit(self, event: dict | None = None) -> None:
        event = event or {}
        self._send(
            "⛔ ERROR — daily loss limit reached\n"
            f"Loss: {_fmt(event.get('daily_loss_percent'))}% / "
            f"limit {_fmt(event.get('limit_percent'))}%\n"
            "New entries are blocked until the next UTC day."
        )

    def on_exchange_disconnected(self, event: dict) -> None:
        name = str(event.get("exchange") or event.get("stream") or "API")
        prev = self._api_ok.get(name)
        self._api_ok[name] = False
        if prev is False:
            return
        self._send(
            f"🔌 API DISCONNECT — {name}\n"
            f"Detail: {event.get('detail', event.get('error', '-'))}"
        )

    def on_exchange_connected(self, event: dict) -> None:
        name = str(event.get("exchange") or event.get("stream") or "API")
        prev = self._api_ok.get(name)
        self._api_ok[name] = True
        if prev is not False:
            return
        self._send(f"✅ API RECONNECTED — {name}")

    # ---- scheduled tick -------------------------------------------------

    def tick(self) -> None:
        if not self.is_enabled():
            return
        self._probe_internet()
        self._probe_exchange_status()
        self._maybe_send_summaries()

    def _probe_internet(self) -> None:
        if self._client is None:
            return
        ok = self._client.probe_api_reachable()
        if self._internet_ok is None:
            self._internet_ok = ok
            return
        if ok and not self._internet_ok:
            self._internet_ok = True
            self._send("✅ INTERNET RECONNECTED")
        elif not ok and self._internet_ok:
            self._internet_ok = False
            self._send("🌐 INTERNET DISCONNECT — Telegram API unreachable")

    def _probe_exchange_status(self) -> None:
        if self._exchange_manager is None:
            return
        try:
            exchanges = self._exchange_manager.enabled()
        except Exception:
            return

        for exchange in exchanges:
            name = exchange.state.exchange.name
            status = exchange.state.status
            ok = status == ConnectionStatus.CONNECTED
            prev = self._api_ok.get(name)
            self._api_ok[name] = ok
            if prev is None:
                continue
            if not ok and prev:
                self._send(
                    f"🔌 API DISCONNECT — {name}\n"
                    f"Status: {status.name}"
                )
            elif ok and prev is False:
                self._send(f"✅ API RECONNECTED — {name}")

    def _maybe_send_summaries(self) -> None:
        settings = self._settings()
        if settings is None:
            return

        now = datetime.now(UTC)
        if now.hour != int(settings.daily_summary_hour_utc) % 24:
            return

        daily_key = now.strftime("%Y-%m-%d")
        if self._last_daily_key != daily_key:
            self._last_daily_key = daily_key
            self.send_daily_summary(now=now)

        if now.weekday() == int(settings.weekly_summary_weekday) % 7:
            year, week, _ = now.isocalendar()
            weekly_key = f"{year}-W{week:02d}"
            if self._last_weekly_key != weekly_key:
                self._last_weekly_key = weekly_key
                self.send_weekly_summary(now=now)

    def send_daily_summary(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        # Summarize the previous UTC day (summary fires at hour 0 by default).
        day_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = day_end - timedelta(days=1)
        stats = self._closed_stats(day_start, day_end)
        open_count = (
            self._position_manager.open_count()
            if self._position_manager is not None
            else 0
        )
        realized = (
            self._risk_manager.realized_pnl_today()
            if self._risk_manager is not None
            else None
        )
        self._send(
            "📊 DAILY SUMMARY\n"
            f"Window: {day_start.date()} UTC\n"
            f"Closed trades: {stats['count']}\n"
            f"Wins / Losses: {stats['wins']} / {stats['losses']}\n"
            f"Net PnL: {_fmt(stats['net_pnl'])}\n"
            f"Open positions: {open_count}\n"
            f"Realized today (breaker): {_fmt(realized)}"
        )

    def send_weekly_summary(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        week_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_end - timedelta(days=7)
        stats = self._closed_stats(week_start, week_end)
        self._send(
            "📈 WEEKLY SUMMARY\n"
            f"Window: {week_start.date()} → {week_end.date()} UTC\n"
            f"Closed trades: {stats['count']}\n"
            f"Wins / Losses: {stats['wins']} / {stats['losses']}\n"
            f"Net PnL: {_fmt(stats['net_pnl'])}"
        )

    def _closed_stats(
        self,
        start: datetime,
        end: datetime,
    ) -> dict:
        empty = {"count": 0, "wins": 0, "losses": 0, "net_pnl": 0.0}
        if self._trade_journal is None:
            return empty

        wins = losses = 0
        net = 0.0
        count = 0
        for entry in self._trade_journal.list_all():
            if entry.status != STATUS_CLOSED or entry.exit_time is None:
                continue
            exit_time = entry.exit_time
            if exit_time.tzinfo is None:
                exit_time = exit_time.replace(tzinfo=UTC)
            if not (start <= exit_time.astimezone(UTC) < end):
                continue
            count += 1
            pnl = float(entry.pnl or 0.0)
            net += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        return {
            "count": count,
            "wins": wins,
            "losses": losses,
            "net_pnl": net,
        }

    def _send(self, text: str) -> None:
        if not self.is_enabled() or self._client is None:
            return
        self._client.send_message(text)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)
