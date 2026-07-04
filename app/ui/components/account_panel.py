import flet as ft


def _info(title, value, color="#FFFFFF"):
    return ft.Container(
        bgcolor="#111827",
        border_radius=10,
        padding=12,
        content=ft.Column(
            spacing=2,
            controls=[
                ft.Text(
                    title,
                    size=10,
                    color="#64748B",
                ),
                ft.Text(
                    value,
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                ),
            ],
        ),
    )


def build_account_panel():
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

                _info("Exchange", "Bybit"),
                _info("Mode", "Paper Trading"),
                _info("Wallet", "$125,420"),
                _info("Available", "$125,420", "#22C55E"),
                _info("Bot Status", "ONLINE", "#22C55E"),
                _info("API", "CONNECTED", "#22C55E"),
            ],
        ),
    )
