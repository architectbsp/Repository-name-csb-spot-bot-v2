from datetime import datetime

import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.core.exchange.models import ExchangeType


_EXCHANGES = [e.name for e in ExchangeType]


def _status_box(title, value, color="#22C55E"):
    icons = {
        "BOT": ft.Icons.PLAY_CIRCLE_FILL,
        "INTERNET": ft.Icons.WIFI,
        "API": ft.Icons.VERIFIED_USER,
        "EXCHANGE": ft.Icons.ACCOUNT_BALANCE,
        "TIME": ft.Icons.SCHEDULE,
    }

    return ft.Container(
        width=160,
        height=60,
        bgcolor="#0B1220",
        border_radius=10,
        padding=10,
        content=ft.Row(
            spacing=10,
            controls=[
                ft.Icon(
                    icons.get(title, ft.Icons.INFO),
                    color=color,
                    size=24,
                ),
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(title, size=10, color="#64748B"),
                        ft.Text(
                            value,
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                        ),
                    ],
                ),
            ],
        ),
    )


def _action(text: str, on_click=None):
    icons = {
        "API": ft.Icons.KEY,
        "TELEGRAM": ft.Icons.SEND,
        "LOG": ft.Icons.DESCRIPTION,
        "SETTINGS": ft.Icons.SETTINGS,
    }

    return ft.Container(
        height=50,
        border_radius=10,
        bgcolor="#0B1220",
        padding=14,
        ink=on_click is not None,
        on_click=(lambda _: on_click(text)) if on_click is not None else None,
        content=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(
                    icons.get(text, ft.Icons.CIRCLE),
                    color="white",
                    size=18,
                ),
                ft.Text(
                    text,
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color="white",
                ),
            ],
        ),
    )


def _exchange(name, active=False, on_select=None):
    def _handle(_event) -> None:
        if on_select is not None:
            on_select(name)

    return ft.Container(
        height=40,
        border_radius=10,
        bgcolor="#2563EB" if active else "#0B1220",
        padding=14,
        ink=on_select is not None,
        on_click=_handle if on_select is not None else None,
        content=ft.Text(
            name,
            size=12,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF",
        ),
    )


def _resolve_active_exchange(snapshot: DashboardSnapshot | None) -> str:
    if snapshot is None:
        return ""
    active = (snapshot.active_exchange or "").strip().upper()
    if active and active != "-":
        return active
    # Legacy snapshots: single exchange_name (not a comma list).
    name = (snapshot.exchange_name or "").strip().upper()
    if name and "," not in name and name != "-":
        return name
    enabled = snapshot.enabled_exchanges or []
    if enabled:
        return str(enabled[0]).strip().upper()
    return ""


def build_top_bar(
    snapshot: DashboardSnapshot | None = None,
    *,
    on_action=None,
    on_exchange_select=None,
):
    if snapshot is None:
        bot = "OFFLINE"
        bot_color = "#EF4444"
        api = "DISCONNECTED"
        api_color = "#EF4444"
        exchange = "-"
        mode = "-"
        mode_color = "#94A3B8"
        # Until a real probe exists, mirror API connectivity as a
        # best-effort "internet" signal (no separate connectivity check).
        internet = "UNKNOWN"
        internet_color = "#94A3B8"
    else:
        bot = "ONLINE" if snapshot.bot_running else "OFFLINE"
        bot_color = "#22C55E" if snapshot.bot_running else "#EF4444"
        api = "CONNECTED" if snapshot.api_connected else "DISCONNECTED"
        api_color = "#22C55E" if snapshot.api_connected else "#EF4444"
        active = _resolve_active_exchange(snapshot)
        exchange = active or snapshot.exchange_name or "-"
        mode = (snapshot.trading_mode or "PAPER").upper()
        mode_color = "#F59E0B" if mode == "PAPER" else "#EF4444"
        internet = "ONLINE" if snapshot.api_connected else "CHECK"
        internet_color = "#22C55E" if snapshot.api_connected else "#F59E0B"

    now = datetime.now().strftime("%H:%M")
    active_name = _resolve_active_exchange(snapshot)

    return ft.Column(
        spacing=12,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            _status_box("BOT", bot, bot_color),
                            _status_box("MODE", mode, mode_color),
                            _status_box("INTERNET", internet, internet_color),
                            _status_box("API", api, api_color),
                            _status_box("EXCHANGE", exchange, "#FFFFFF"),
                            _status_box("TIME", now, "#FFFFFF"),
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            _action("API", on_action),
                            _action("TELEGRAM", on_action),
                            _action("LOG", on_action),
                            _action("SETTINGS", on_action),
                        ],
                    ),
                ],
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            _exchange(
                                name,
                                active=(name == active_name),
                                on_select=on_exchange_select,
                            )
                            for name in _EXCHANGES
                        ],
                    ),
                ],
            ),
        ],
    )
