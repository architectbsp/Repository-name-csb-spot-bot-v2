import flet as ft


# Keys for every nav item. Only DASHBOARD and SETTINGS are currently wired
# to a real view (see app.py); the rest remain visual placeholders until
# their respective views are built, but are listed here so adding a view
# later only means adding one entry to _WIRED_VIEWS in app.py.
DASHBOARD = "dashboard"
SCANNER = "scanner"
MARKET = "market"
SIGNALS = "signals"
POSITIONS = "positions"
PORTFOLIO = "portfolio"
LOGS = "logs"
SETTINGS = "settings"

_MENU_ITEMS = (
    (DASHBOARD, "Dashboard"),
    (SCANNER, "Scanner"),
    (MARKET, "Market"),
    (SIGNALS, "Signals"),
    (POSITIONS, "Positions"),
    (PORTFOLIO, "Portfolio"),
    (LOGS, "Logs"),
    (SETTINGS, "Settings"),
)


def _menu_item(key: str, title: str, active: bool, on_click) -> ft.Container:
    return ft.Container(
        height=42,
        border_radius=10,
        bgcolor="#2563EB" if active else "#0F172A",
        padding=12,
        ink=True,
        on_click=(lambda _: on_click(key)) if on_click else None,
        content=ft.Row(
            spacing=10,
            controls=[
                ft.Text("◉" if active else "○", color="#FFFFFF", size=11),
                ft.Text(
                    title,
                    size=13,
                    weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500,
                    color="#FFFFFF" if active else "#CBD5E1",
                ),
            ],
        ),
    )


def build_sidebar(active: str = DASHBOARD, on_navigate=None) -> ft.Container:
    return ft.Container(
        width=220,
        bgcolor="#0B1220",
        border_radius=16,
        padding=20,
        content=ft.Column(
            expand=True,
            spacing=8,
            controls=[
                ft.Text(
                    "CSB",
                    size=36,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                ),
                ft.Text(
                    "Spot Bot v2",
                    size=12,
                    color="#64748B",
                ),
                ft.Divider(height=25),
                *[
                    _menu_item(key, title, key == active, on_navigate)
                    for key, title in _MENU_ITEMS
                ],
                ft.Container(expand=True),
                ft.Divider(),
                ft.Text(
                    "SYSTEM",
                    size=10,
                    color="#64748B",
                ),
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Text("●", color="#22C55E", size=12),
                        ft.Text(
                            "ONLINE",
                            size=12,
                            color="#CBD5E1",
                        ),
                    ],
                ),
            ],
        ),
    )
