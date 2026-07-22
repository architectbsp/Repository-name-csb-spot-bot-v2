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


def _action(text):
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


def _exchange(name, active=False):
    return ft.Container(
        height=40,
        border_radius=10,
        bgcolor="#2563EB" if active else "#0B1220",
        padding=14,
        content=ft.Text(
            name,
            size=12,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF",
        ),
    )


def build_top_bar(snapshot: DashboardSnapshot | None = None):
    if snapshot is None:
        bot = "OFFLINE"
        bot_color = "#EF4444"
        api = "DISCONNECTED"
        api_color = "#EF4444"
        exchange = "-"
        # Until a real probe exists, mirror API connectivity as a
        # best-effort "internet" signal (no separate connectivity check).
        internet = "UNKNOWN"
        internet_color = "#94A3B8"
    else:
        bot = "ONLINE" if snapshot.bot_running else "OFFLINE"
        bot_color = "#22C55E" if snapshot.bot_running else "#EF4444"
        api = "CONNECTED" if snapshot.api_connected else "DISCONNECTED"
        api_color = "#22C55E" if snapshot.api_connected else "#EF4444"
        exchange = snapshot.exchange_name
        internet = "ONLINE" if snapshot.api_connected else "CHECK"
        internet_color = "#22C55E" if snapshot.api_connected else "#F59E0B"

    now = datetime.now().strftime("%H:%M")
    active_exchange = (snapshot.exchange_name if snapshot else "").upper()

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
                            _status_box("INTERNET", internet, internet_color),
                            _status_box("API", api, api_color),
                            _status_box("EXCHANGE", exchange, "#FFFFFF"),
                            _status_box("TIME", now, "#FFFFFF"),
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            _action("API"),
                            _action("TELEGRAM"),
                            _action("LOG"),
                            _action("SETTINGS"),
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
                            _exchange(name, active=(name == active_exchange))
                            for name in _EXCHANGES
                        ],
                    ),
                ],
            ),
        ],
    )
