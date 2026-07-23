"""
Sprint 11 -- Telegram service unit tests (events + command auth).

Uses an in-memory fake client; never hits the real Bot API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.config.settings import AppSettings, TelegramSettings
from app.core.event_bus.event_bus import EventBus
from app.core.services.telegram_notifier import TelegramNotifier


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.message_targets: list[str | None] = []
        self.configured = True
        self.updates: list[dict] = []

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        self.messages.append(text)
        self.message_targets.append(chat_id)
        return True

    def get_updates(self, *, timeout: int = 0, limit: int = 20) -> list[dict]:
        batch = list(self.updates)
        self.updates.clear()
        return batch

    def probe_api_reachable(self) -> bool:
        return True

    def close(self) -> None:
        return None


def make_notifier(client=None) -> TelegramNotifier:
    client = client or FakeClient()
    notifier = TelegramNotifier(client)
    config = AppSettings()
    config.telegram = TelegramSettings(
        bot_token="token",
        chat_id="999",
        admin_chat_id="999",
        enabled=True,
    )
    notifier.set_config(config)
    return notifier


def test_buy_and_sell_events_call_send_with_expected_fields():
    """BUY/SELL event'leri tetiklendiğinde bildirim doğru parametrelerle gider."""
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
            "position": SimpleNamespace(
                pnl=10.0,
                pnl_percent=5.0,
                quantity=1.0,
            ),
        },
    )

    assert len(client.messages) == 2
    buy, sell = client.messages
    assert "BUY" in buy
    assert "BTC/USDT" in buy
    assert "100" in buy
    assert "0.5" in buy
    assert "STOP" in sell or "TRAILING_STOP" in sell
    assert "ETH/USDT" in sell
    assert "10" in sell
    assert "5" in sell
    assert "TRAILING_STOP" in sell


def test_authorized_status_command_replies():
    client = FakeClient()
    notifier = make_notifier(client)
    positions = MagicMock()
    positions.get_open_positions.return_value = []
    positions.open_count.return_value = 0
    positions.entries_frozen = False
    notifier.set_position_manager(positions)

    assert notifier.handle_command("999", "/status") is True
    assert client.messages
    assert "STATUS" in client.messages[-1]
    assert client.message_targets[-1] == "999"


def test_unauthorized_chat_id_is_rejected(caplog):
    """Yetkisiz Chat ID komutları reddedilir ve güvenlik uyarısı loglanır."""
    import logging

    client = FakeClient()
    notifier = make_notifier(client)

    with caplog.at_level(logging.WARNING):
        assert notifier.handle_command("evil-chat", "/emergency") is False

    assert client.messages == []
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "SECURITY" in joined or "unauthorized" in joined
    assert "evil-chat" in joined
    assert "/emergency" in joined


def test_emergency_command_triggers_risk_manager():
    client = FakeClient()
    notifier = make_notifier(client)
    risk = MagicMock()
    risk.emergency_exit_all.return_value = 2
    notifier.set_risk_manager(risk)

    assert notifier.handle_command("999", "/emergency") is True
    risk.emergency_exit_all.assert_called_once()
    assert "EMERGENCY" in client.messages[-1]
    assert "2" in client.messages[-1]


def test_poll_commands_from_get_updates():
    client = FakeClient()
    notifier = make_notifier(client)
    positions = MagicMock()
    positions.get_open_positions.return_value = []
    notifier.set_position_manager(positions)

    client.updates = [
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 999},
                "text": "/status",
            },
        }
    ]
    notifier.tick()
    assert any("STATUS" in m for m in client.messages)
