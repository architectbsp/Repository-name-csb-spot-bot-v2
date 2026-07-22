"""
Sprint 12 -- Live Dashboard panels render from a DashboardSnapshot
(including the empty/zero state) without needing a running Flet Page.
"""

from datetime import UTC, datetime

import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, Report24h
from app.ui.components.account_panel import build_account_panel
from app.ui.components.dashboard_cards import build_dashboard_cards
from app.ui.components.report_24h import build_report_24h
from app.ui.components.top_bar import build_top_bar


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)


def _texts(control) -> list[str]:
    return [
        c.value
        for c in _walk(control)
        if isinstance(c, ft.Text) and isinstance(c.value, str)
    ]


def test_dashboard_cards_render_live_snapshot_values():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        quote_balance=1250.5,
        daily_pnl_percent=2.5,
        open_position_count=3,
        active_signal_count=7,
    )

    texts = _texts(build_dashboard_cards(snap))

    assert "$1,250.50" in texts
    assert "+2.50%" in texts
    assert "03" in texts
    assert "7" in texts


def test_account_panel_reflects_bot_and_api_status():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        exchange_name="BINANCE",
        testnet=True,
        bot_running=True,
        api_connected=True,
        quote_balance=100.0,
        available_balance=100.0,
    )

    texts = _texts(build_account_panel(snap))

    assert "BINANCE" in texts
    assert "Testnet" in texts
    assert "ONLINE" in texts
    assert "CONNECTED" in texts


def test_top_bar_highlights_the_active_exchange():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        exchange_name="OKX",
        bot_running=False,
        api_connected=False,
    )

    bar = build_top_bar(snap)
    texts = _texts(bar)

    assert "OFFLINE" in texts
    assert "OKX" in texts
    assert "DISCONNECTED" in texts


def test_report_24h_renders_zero_state_cleanly():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        report_24h=Report24h(),
    )

    texts = _texts(build_report_24h(snap))

    assert "0" in texts
    assert "0.00 USDT" in texts or "+0.00 USDT" in texts
