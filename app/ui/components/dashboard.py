import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.components.account_panel import build_account_panel
from app.ui.components.bot_log import build_bot_log
from app.ui.components.coin_table import build_coin_table
from app.ui.components.cooldown import build_cooldown
from app.ui.components.open_positions import build_open_positions
from app.ui.components.recent_signals import build_recent_signals
from app.ui.components.report_24h import build_report_24h
from app.ui.components.trade_history import build_trade_history


def build_dashboard(
    engine=None,
    page=None,
    snapshot: DashboardSnapshot | None = None,
):
    left = ft.Column(
        expand=78,
        spacing=15,
        controls=[
            ft.Row(
                expand=58,
                spacing=15,
                controls=[
                    ft.Container(
                        expand=32,
                        content=build_coin_table(engine, page, snapshot),
                    ),
                    ft.Container(
                        expand=68,
                        content=build_open_positions(engine, page, snapshot),
                    ),
                ],
            ),
            ft.Row(
                expand=24,
                spacing=15,
                controls=[
                    ft.Container(
                        expand=1,
                        content=build_recent_signals(snapshot),
                    ),
                    ft.Container(expand=1, content=build_cooldown(snapshot)),
                    ft.Container(
                        expand=1,
                        content=build_trade_history(snapshot),
                    ),
                ],
            ),
            ft.Row(
                expand=18,
                spacing=15,
                controls=[
                    ft.Container(expand=1, content=build_bot_log(snapshot)),
                ],
            ),
        ],
    )

    right = ft.Column(
        expand=22,
        spacing=15,
        controls=[
            ft.Container(expand=82, content=build_account_panel(snapshot)),
            ft.Container(expand=18, content=build_report_24h(snapshot)),
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
