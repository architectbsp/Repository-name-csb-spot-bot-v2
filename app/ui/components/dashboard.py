import flet as ft

from app.ui.components.coin_table import build_coin_table
from app.ui.components.account_panel import build_account_panel
from app.ui.components.open_positions import build_open_positions
from app.ui.components.bot_log import build_bot_log
from app.ui.components.recent_signals import build_recent_signals
from app.ui.components.cooldown import build_cooldown
from app.ui.components.trade_history import build_trade_history
from app.ui.components.report_24h import build_report_24h


def _panel(title: str):
    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border=ft.Border(left=ft.BorderSide(1, "#1B2435"), right=ft.BorderSide(1, "#1B2435"), top=ft.BorderSide(1, "#1B2435"), bottom=ft.BorderSide(1, "#1B2435")),
        border_radius=12,
        padding=15,
        content=ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Text(
                    title,
                    color="white",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                )
            ],
        ),
    )


def build_dashboard(engine=None, page=None):
    left = ft.Column(
        expand=78,
        spacing=15,
        controls=[
            ft.Row(
                expand=58,
                spacing=15,
                controls=[
                    ft.Container(expand=32, content=build_coin_table(engine, page)),
                    ft.Container(
                        expand=68,
                        content=build_open_positions(engine, page),
                    ),
                ],
            ),
            ft.Row(
                expand=24,
                spacing=15,
                controls=[
                    ft.Container(expand=1, content=build_recent_signals()),
                    ft.Container(expand=1, content=build_cooldown()),
                    ft.Container(expand=1, content=build_trade_history()),
                ],
            ),
            ft.Row(
                expand=18,
                spacing=15,
                controls=[
                    ft.Container(expand=1, content=build_bot_log()),
                ],
            ),
        ],
    )

    right = ft.Column(
        expand=22,
        spacing=15,
        controls=[
            ft.Container(expand=82, content=build_account_panel()),
            ft.Container(expand=18, content=build_report_24h()),
        ],
    )

    return ft.Row(
        expand=True,
        spacing=15,
        controls=[
            left,
            right,
        ],
    )
