"""
Sprint 11 -- Telegram remote command handler.

Authorized ``telegram_admin_chat_id`` (or notification chat_id fallback)
may invoke:

  /status   -- open positions, balance, run mode
  /summary  -- today + week PnL / win rate / trade count
  /emergency -- RiskManager.emergency_exit_all + freeze entries

Unauthorized chat IDs are rejected with a security warning log; no reply
is sent (avoids confirming the bot exists to strangers).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.domain.trade_journal import STATUS_CLOSED
from app.core.security.redact import safe_error_text


logger = logging.getLogger(__name__)

_KNOWN_COMMANDS = frozenset({"/status", "/summary", "/emergency", "/help"})


def normalize_command(text: str) -> str:
    """`/status@MyBot extra` → `/status`."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return ""
    first = raw.split()[0]
    return first.split("@", 1)[0].lower()


class TelegramCommandHandler:
    def __init__(self, notifier) -> None:
        # Notifier owns client / config / risk / journal / positions.
        self._notifier = notifier

    def admin_chat_id(self) -> str:
        settings = self._notifier._settings()
        if settings is None:
            return ""
        admin = (getattr(settings, "admin_chat_id", "") or "").strip()
        if admin:
            return admin
        return (settings.chat_id or "").strip()

    def is_authorized(self, chat_id: str) -> bool:
        admin = self.admin_chat_id()
        if not admin:
            return False
        return str(chat_id).strip() == admin

    def handle(self, chat_id: str, text: str) -> bool:
        """
        Process one inbound message. Returns True if a known command was
        handled (authorized). Unauthorized attempts return False after
        logging a security warning.
        """
        cmd = normalize_command(text)
        if not cmd or cmd not in _KNOWN_COMMANDS:
            return False

        if not self.is_authorized(chat_id):
            logger.warning(
                "[TELEGRAM] SECURITY unauthorized command chat_id=%s cmd=%s",
                chat_id,
                cmd,
            )
            return False

        if cmd == "/status":
            self._notifier._send(self._format_status(), chat_id=chat_id)
        elif cmd == "/summary":
            self._notifier._send(self._format_summary(), chat_id=chat_id)
        elif cmd == "/emergency":
            self._run_emergency(chat_id)
        elif cmd == "/help":
            self._notifier._send(
                "Commands:\n/status\n/summary\n/emergency\n/help",
                chat_id=chat_id,
            )
        return True

    def _run_emergency(self, chat_id: str) -> None:
        risk = self._notifier._risk_manager
        if risk is None or not hasattr(risk, "emergency_exit_all"):
            self._notifier._send(
                "⛔ EMERGENCY unavailable — RiskManager not wired",
                chat_id=chat_id,
            )
            return
        try:
            closed = int(risk.emergency_exit_all() or 0)
        except Exception as exc:
            logger.error(
                "[TELEGRAM] emergency_exit_all failed: %s",
                safe_error_text(exc),
            )
            self._notifier._send(
                f"⛔ EMERGENCY failed: {type(exc).__name__}",
                chat_id=chat_id,
            )
            return
        self._notifier._send(
            "🚨 EMERGENCY EXIT executed\n"
            f"Closed positions: {closed}\n"
            "New BUY entries are frozen until operator unfreezes.",
            chat_id=chat_id,
        )

    def _format_status(self) -> str:
        n = self._notifier
        open_rows: list[str] = []
        open_count = 0
        if n._position_manager is not None:
            try:
                positions = list(n._position_manager.get_open_positions())
            except Exception:
                positions = []
            open_count = len(positions)
            for pos in positions[:20]:
                symbol = getattr(pos, "symbol", "?")
                entry = getattr(pos, "entry_price", None)
                stop = getattr(pos, "stop_price", None)
                exch = getattr(pos, "exchange", "")
                venue = f" [{exch}]" if exch else ""
                open_rows.append(
                    f"• {symbol}{venue} entry={_fmt(entry)} stop={_fmt(stop)}"
                )

        balance = "-"
        if n._exchange_manager is not None:
            try:
                if hasattr(n._exchange_manager, "total_quote_balance"):
                    balance = _fmt(n._exchange_manager.total_quote_balance())
                elif hasattr(n._exchange_manager, "get_quote_balance"):
                    # Single-venue fallback.
                    enabled = []
                    if hasattr(n._exchange_manager, "enabled_exchange_types"):
                        enabled = list(
                            n._exchange_manager.enabled_exchange_types()
                        )
                    if enabled:
                        balance = _fmt(
                            n._exchange_manager.get_quote_balance(enabled[0])
                        )
            except Exception:
                balance = "-"

        frozen = False
        if n._risk_manager is not None:
            frozen = bool(getattr(n._risk_manager, "_entries_frozen", False))
        if n._position_manager is not None:
            frozen = frozen or bool(
                getattr(n._position_manager, "entries_frozen", False)
            )

        hours = "7/24"
        if n._config is not None:
            st = n._config.strategy
            if bool(int(getattr(st, "trading_hours_enabled", 0) or 0)):
                start = getattr(st, "trading_start_time", "08:00")
                end = getattr(st, "trading_end_time", "23:00")
                hours = f"window {start}–{end} UTC"

        mode = "FROZEN (no new BUY)" if frozen else f"ACTIVE ({hours})"
        body = (
            "📡 STATUS\n"
            f"Mode: {mode}\n"
            f"Balance: {balance}\n"
            f"Open positions: {open_count}\n"
        )
        if open_rows:
            body += "\n".join(open_rows)
        else:
            body += "(none)"
        return body

    def _format_summary(self) -> str:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=now.weekday())

        today = self._notifier._closed_stats(day_start, now + timedelta(seconds=1))
        week = self._notifier._closed_stats(week_start, now + timedelta(seconds=1))

        return (
            "📊 SUMMARY\n"
            f"Today ({day_start.date()} UTC)\n"
            f"  Trades: {today['count']}\n"
            f"  Win rate: {_win_rate(today)}%\n"
            f"  Net PnL: {_fmt(today['net_pnl'])}\n"
            f"Week (from {week_start.date()} UTC)\n"
            f"  Trades: {week['count']}\n"
            f"  Win rate: {_win_rate(week)}%\n"
            f"  Net PnL: {_fmt(week['net_pnl'])}"
        )


def _win_rate(stats: dict) -> str:
    count = int(stats.get("count") or 0)
    wins = int(stats.get("wins") or 0)
    if count <= 0:
        return "0"
    return f"{(wins / count) * 100:.1f}"


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)
