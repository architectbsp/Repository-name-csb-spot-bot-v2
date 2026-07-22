import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.formatting import money_usd


def _info(title, value, color="#FFFFFF"):
    return ft.Container(
        bgcolor="#111827",
        border_radius=10,
        padding=12,
        content=ft.Column(
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
    )


def build_account_panel(snapshot: DashboardSnapshot | None = None):
    if snapshot is None:
        exchange = "-"
        mode = "-"
        wallet = "-"
        available = "-"
        bot_status = "OFFLINE"
        bot_color = "#EF4444"
        api = "DISCONNECTED"
        api_color = "#EF4444"
    else:
        exchange = snapshot.exchange_name
        mode = "Testnet" if snapshot.testnet else "Live"
        wallet = money_usd(snapshot.quote_balance)
        available = money_usd(snapshot.available_balance)
        bot_status = "ONLINE" if snapshot.bot_running else "OFFLINE"
        bot_color = "#22C55E" if snapshot.bot_running else "#EF4444"
        api = "CONNECTED" if snapshot.api_connected else "DISCONNECTED"
        api_color = "#22C55E" if snapshot.api_connected else "#EF4444"

    return ft.Container(
        width=320,
        bgcolor="#0B1220",
        border_radius=14,
        padding=18,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text(
                    "ACCOUNT",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                ),
                _info("Exchange", exchange),
                _info("Mode", mode),
                _info("Wallet", wallet),
                _info("Available", available, "#22C55E"),
                _info("Bot Status", bot_status, bot_color),
                _info("API", api, api_color),
            ],
        ),
    )
