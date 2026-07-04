import flet as ft


def _row(symbol, direction, change, status):
    color = "#22C55E" if direction == "LONG" else "#EF4444"

    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(symbol, color="white", size=12, expand=2),
            ft.Text(direction, color=color, size=12, expand=1),
            ft.Text(change, color=color, size=12, expand=1),
            ft.Text(status, color="#F59E0B", size=12, expand=2),
        ],
    )


def build_recent_signals():
    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border=ft.Border(
            left=ft.BorderSide(1, "#1B2435"),
            top=ft.BorderSide(1, "#1B2435"),
            right=ft.BorderSide(1, "#1B2435"),
            bottom=ft.BorderSide(1, "#1B2435"),
        ),
        border_radius=12,
        padding=15,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            "WATCH LIST",
                            color="white",
                            weight=ft.FontWeight.BOLD,
                            size=15,
                        ),
                        ft.Text("18", color="#C5CDD8"),
                    ],
                ),
                _row("INJ/USDT", "LONG", "+2.67%", "%6 Bekleniyor"),
                _row("RNDR/USDT", "LONG", "+4.12%", "%6 Bekleniyor"),
                _row("TIA/USDT", "LONG", "+3.15%", "%6 Bekleniyor"),
                _row("OP/USDT", "SHORT", "-3.01%", "Dip Takip"),
                _row("ARB/USDT", "SHORT", "-2.78%", "Dip Takip"),
                ft.Divider(height=10, color="#1B2435"),
                ft.Text(
                    "Tümünü Görüntüle",
                    color="#C5CDD8",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
