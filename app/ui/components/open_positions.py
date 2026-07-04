import flet as ft


def _badge(text, color):
    return ft.Container(
        bgcolor=color,
        border_radius=20,
        padding=6,
        content=ft.Text(
            text,
            size=10,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF",
        ),
    )


def _position(symbol, side, entry, current, pnl):
    pnl_color = "#22C55E" if pnl.startswith("+") else "#EF4444"
    side_color = "#22C55E" if side == "LONG" else "#EF4444"

    return ft.Container(
        bgcolor="#111827",
        border_radius=10,
        padding=12,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(symbol, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                        _badge(side, side_color),
                    ],
                ),
                ft.Column(
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                    controls=[
                        ft.Text(f"Entry : {entry}", size=11, color="#94A3B8"),
                        ft.Text(f"Now : {current}", size=11, color="#94A3B8"),
                        ft.Text(
                            pnl,
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=pnl_color,
                        ),
                    ],
                ),
            ],
        ),
    )


def build_open_positions():
    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border_radius=14,
        padding=18,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Text(
                    "OPEN POSITIONS",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                ),
                _position("BTCUSDT", "LONG", "118100", "118420", "+0.27%"),
                _position("ETHUSDT", "SHORT", "3940", "3920", "+0.51%"),
                _position("SOLUSDT", "LONG", "180", "184", "+2.22%"),
            ],
        ),
    )
