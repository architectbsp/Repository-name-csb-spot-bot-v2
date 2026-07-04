import flet as ft


def _row(symbol, stop_time, remaining):
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(symbol, color="white", size=12, expand=2),
            ft.Text(stop_time, color="#C5CDD8", size=12, expand=2),
            ft.Text(remaining, color="#22C55E", size=12, expand=1),
        ],
    )


def build_cooldown():
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
                            "COOLDOWN",
                            color="white",
                            size=15,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text("6", color="#C5CDD8"),
                    ],
                ),
                _row("AAVE/USDT", "08:45:12", "11:32:41"),
                _row("APE/USDT", "07:22:18", "10:09:47"),
                _row("BLUR/USDT", "06:35:05", "09:22:34"),
                _row("SAND/USDT", "05:12:44", "08:01:13"),
                _row("MANA/USDT", "04:01:33", "06:49:02"),
                ft.Divider(height=10, color="#1B2435"),
                ft.Text(
                    "Tümünü Görüntüle",
                    color="#C5CDD8",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
