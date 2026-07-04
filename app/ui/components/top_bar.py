import flet as ft


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


def build_top_bar():
    return ft.Column(
        spacing=12,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            _status_box("BOT", "READY"),
                            _status_box("INTERNET", "ONLINE"),
                            _status_box("API", "CONNECTED"),
                            _status_box("EXCHANGE", "BYBIT", "#FFFFFF"),
                            _status_box("TIME", "16:53", "#FFFFFF"),
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
                            _exchange("BINANCE"),
                            _exchange("KRAKEN"),
                            _exchange("MEXC"),
                            _exchange("BYBIT", True),
                            _exchange("OKX"),
                        ],
                    ),
                ],
            ),
        ],
    )
