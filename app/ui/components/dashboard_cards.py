import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.formatting import money_usd, signed_percent


def _card(title, value, subtitle, color):
    return ft.Container(
        expand=True,
        height=95,
        bgcolor="#0B1220",
        border_radius=14,
        padding=16,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column(
                    spacing=3,
                    controls=[
                        ft.Text(title, size=11, color="#64748B"),
                        ft.Text(
                            value,
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                        ),
                        ft.Text(subtitle, size=11, color="#94A3B8"),
                    ],
                ),
                ft.Container(
                    width=42,
                    height=42,
                    border_radius=21,
                    bgcolor="#111827",
                    content=ft.Text("●", color=color, size=16),
                ),
            ],
        ),
    )


def build_dashboard_cards(snapshot: DashboardSnapshot | None = None):
    if snapshot is None:
        portfolio = "-"
        daily = "-"
        daily_color = "#94A3B8"
        positions = "0"
        signals = "0"
    else:
        portfolio = money_usd(snapshot.quote_balance)
        daily = signed_percent(snapshot.daily_pnl_percent)
        daily_color = (
            "#22C55E"
            if (snapshot.daily_pnl_percent or 0) >= 0
            else "#EF4444"
        )
        positions = f"{snapshot.open_position_count:02d}"
        signals = str(snapshot.active_signal_count)

    return ft.Row(
        spacing=15,
        controls=[
            _card("PORTFOLIO", portfolio, "Total Balance", "#FFFFFF"),
            _card("DAILY PNL", daily, "Today", daily_color),
            _card("POSITIONS", positions, "Open Trades", "#3B82F6"),
            _card("SIGNALS", signals, "Active Signals", "#F59E0B"),
        ],
    )
