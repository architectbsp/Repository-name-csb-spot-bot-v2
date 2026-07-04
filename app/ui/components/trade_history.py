import flet as ft


def _row(symbol, direction, pnl, result):
    color = "#22C55E" if result == "KÂR" else "#EF4444"

    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(symbol, color="white", size=12, expand=2),
            ft.Text(direction, color="#22C55E", size=12, expand=1),
            ft.Text(pnl, color=color, size=12, expand=1),
            ft.Text(result, color=color, size=12, expand=1),
        ],
    )


def build_trade_history():
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
                            "TRADE HISTORY",
                            color="white",
                            size=15,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text("10", color="#C5CDD8"),
                    ],
                ),
                _row("EOS/USDT", "LONG", "+7.95%", "KÂR"),
                _row("CHZ/USDT", "LONG", "+5.51%", "KÂR"),
                _row("LDO/USDT", "LONG", "+4.71%", "KÂR"),
                _row("FTM/USDT", "LONG", "-4.95%", "STOP"),
                _row("ELF/USDT", "LONG", "-4.90%", "STOP"),
                ft.Divider(height=10, color="#1B2435"),
                ft.Text(
                    "Tüm Geçmişi Görüntüle",
                    color="#C5CDD8",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
