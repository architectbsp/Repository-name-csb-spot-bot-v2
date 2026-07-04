import flet as ft


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
                        ft.Text(
                            title,
                            size=11,
                            color="#64748B",
                        ),
                        ft.Text(
                            value,
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                        ),
                        ft.Text(
                            subtitle,
                            size=11,
                            color="#94A3B8",
                        ),
                    ],
                ),
                ft.Container(
                    width=42,
                    height=42,
                    border_radius=21,
                    bgcolor="#111827",
                    alignment=ft.MainAxisAlignment.CENTER,
                    content=ft.Text(
                        "●",
                        color=color,
                        size=16,
                    ),
                ),
            ],
        ),
    )


def build_dashboard_cards():
    return ft.Row(
        spacing=15,
        controls=[
            _card("PORTFOLIO", "$125,420", "Total Balance", "#FFFFFF"),
            _card("DAILY PNL", "+2.84%", "Today", "#22C55E"),
            _card("POSITIONS", "08", "Open Trades", "#3B82F6"),
            _card("SIGNALS", "23", "Active Signals", "#F59E0B"),
        ],
    )
