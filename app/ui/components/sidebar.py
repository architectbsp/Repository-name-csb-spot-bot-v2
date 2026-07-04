import flet as ft


def _menu_item(title: str, active: bool = False):
    return ft.Container(
        height=42,
        border_radius=10,
        bgcolor="#2563EB" if active else "#0F172A",
        padding=12,
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


def build_sidebar():
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
                _menu_item("Dashboard", True),
                _menu_item("Scanner"),
                _menu_item("Market"),
                _menu_item("Signals"),
                _menu_item("Positions"),
                _menu_item("Portfolio"),
                _menu_item("Logs"),
                _menu_item("Settings"),
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
