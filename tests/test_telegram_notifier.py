"""
Sprint 11 -- Telegram notifications: formatting, event routing, summary
windows and connectivity state-change alerts. Uses an in-memory fake
client so tests never hit the real Bot API.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.core.config.settings import AppSettings, TelegramSettings
from app.core.domain.trade_journal import STATUS_CLOSED, TradeJournalEntry
from app.core.event_bus.event_bus import EventBus
from app.core.exchange.models import ConnectionStatus, ExchangeState, ExchangeType
from app.core.services.order_execution import ExecutionOutcome
from app.core.services.telegram_client import TelegramClient
from app.core.services.telegram_notifier import TelegramNotifier


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.reachable = True
        self.configured = True

    def send_message(self, text: str, *, parse_mode: str | None = None) -> bool:
        self.messages.append(text)
        return True

    def probe_api_reachable(self) -> bool:
        return self.reachable

    def close(self) -> None:
        return None


class DummyJournal:
    def __init__(self, entries=None):
        self._entries = entries or []

    def list_all(self):
        return list(self._entries)


class DummyRisk:
    def realized_pnl_today(self):
        return -12.5


class DummyPositions:
    def open_count(self):
        return 2


class DummyExchange:
    def __init__(self, name, status):
        self.state = ExchangeState(
            exchange=name,
            enabled=True,
            status=status,
        )


class DummyExchangeManager:
    def __init__(self, exchanges):
        self._exchanges = exchanges

    def enabled(self):
        return list(self._exchanges)


def make_notifier(client=None, **kwargs) -> TelegramNotifier:
    client = client or FakeClient()
    notifier = TelegramNotifier(client)
    config = AppSettings()
    config.telegram = TelegramSettings(
        bot_token="token",
        chat_id="123",
        enabled=True,
        daily_summary_hour_utc=0,
        weekly_summary_weekday=0,
        connectivity_probe_seconds=30,
    )
    notifier.set_config(config)
    if "journal" in kwargs:
        notifier.set_trade_journal(kwargs["journal"])
    if "risk" in kwargs:
        notifier.set_risk_manager(kwargs["risk"])
    if "positions" in kwargs:
        notifier.set_position_manager(kwargs["positions"])
    if "exchange_manager" in kwargs:
        notifier.set_exchange_manager(kwargs["exchange_manager"])
    return notifier


def test_buy_sell_stop_and_error_messages():
    client = FakeClient()
    notifier = make_notifier(client)
    bus = EventBus()
    notifier.set_event_bus(bus)
    notifier.initialize()

    bus.publish(
        "position.opened",
        {
            "symbol": "BTC/USDT",
            "exchange": "BINANCE",
            "entry_price": 100.0,
            "quantity": 0.5,
            "stop_price": 90.0,
        },
    )
    bus.publish(
        "position.closed",
        {
            "symbol": "ETH/USDT",
            "exchange": "BYBIT",
            "reason": "TRAILING_STOP",
            "price": 200.0,
            "position": SimpleNamespace(pnl=10.0, pnl_percent=5.0),
        },
    )
    bus.publish(
        "position.closed",
        {
            "symbol": "SOL/USDT",
            "reason": "MANUAL_CLOSE",
            "price": 50.0,
            "position": SimpleNamespace(pnl=-1.0, pnl_percent=-2.0),
        },
    )
    bus.publish(
        "order.needs_manual_review",
        {
            "symbol": "X/USDT",
            "side": "BUY",
            "outcome": ExecutionOutcome.UNRECONCILED,
            "error": "timeout",
        },
    )

    joined = "\n---\n".join(client.messages)
    assert "BUY" in joined and "BTC/USDT" in joined
    assert "STOP" in joined and "TRAILING_STOP" in joined
    assert "SELL" in joined and "MANUAL_CLOSE" in joined
    assert "ERROR" in joined and "manual review" in joined


def test_disabled_notifier_sends_nothing():
    client = FakeClient()
    notifier = make_notifier(client)
    notifier._config.telegram.enabled = False

    notifier.on_position_opened({"symbol": "BTC/USDT", "entry_price": 1})
    assert client.messages == []


def test_internet_disconnect_only_on_state_change():
    client = FakeClient()
    notifier = make_notifier(client)
    notifier._internet_ok = True

    client.reachable = False
    notifier._probe_internet()
    notifier._probe_internet()

    assert sum("INTERNET DISCONNECT" in m for m in client.messages) == 1

    client.reachable = True
    notifier._probe_internet()
    assert any("INTERNET RECONNECTED" in m for m in client.messages)


def test_api_disconnect_from_exchange_status_probe():
    client = FakeClient()
    exchange = DummyExchange(ExchangeType.BINANCE, ConnectionStatus.CONNECTED)
    manager = DummyExchangeManager([exchange])
    notifier = make_notifier(client, exchange_manager=manager)

    notifier._probe_exchange_status()  # seed
    exchange.state.status = ConnectionStatus.ERROR
    notifier._probe_exchange_status()
    notifier._probe_exchange_status()

    assert sum("API DISCONNECT" in m for m in client.messages) == 1


def test_daily_summary_uses_previous_utc_day_window():
    now = datetime(2026, 7, 23, 0, 5, tzinfo=UTC)
    entries = [
        TradeJournalEntry(
            symbol="A/USDT",
            entry_time=now - timedelta(days=1, hours=2),
            entry_price=1.0,
            quantity=1.0,
            entry_reason="PATH_A",
            status=STATUS_CLOSED,
            exit_time=now - timedelta(hours=12),
            exit_price=1.1,
            pnl=10.0,
        ),
        TradeJournalEntry(
            symbol="B/USDT",
            entry_time=now - timedelta(days=3),
            entry_price=1.0,
            quantity=1.0,
            entry_reason="PATH_A",
            status=STATUS_CLOSED,
            exit_time=now - timedelta(days=2),
            exit_price=0.9,
            pnl=-5.0,
        ),
    ]
    client = FakeClient()
    notifier = make_notifier(
        client,
        journal=DummyJournal(entries),
        risk=DummyRisk(),
        positions=DummyPositions(),
    )

    notifier.send_daily_summary(now=now)

    text = client.messages[-1]
    assert "DAILY SUMMARY" in text
    assert "Closed trades: 1" in text
    assert "Net PnL: 10" in text
    assert "Open positions: 2" in text


def test_telegram_client_skips_when_unconfigured():
    client = TelegramClient("", "")
    assert client.configured is False
    assert client.send_message("hi") is False


def test_load_telegram_settings_requires_credentials(monkeypatch):
    from app.core.config.settings import load_telegram_settings

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)

    settings = load_telegram_settings()
    assert settings.enabled is True
    assert settings.chat_id == "42"

    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    settings = load_telegram_settings()
    assert settings.enabled is False
