import flet as ft

HEADERS = [
    (1, "#"),
    (4, "COIN"),
    (3, "SON FİYAT"),
    (2, "24H %"),
    (3, "24H HACİM"),
    (2, "SİNYAL"),
    (2, "DURUM"),
]


def _toolbar():
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(
                "SPOT COIN LİSTESİ",
                size=18,
                weight=ft.FontWeight.BOLD,
                color="white",
            ),
            ft.Row(
                spacing=8,
                controls=[
                    ft.Container(
                        width=180,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        padding=12,
                        content=ft.Text(
                            "Coin ara...",
                            color="#6B7280",
                            size=12,
                        ),
                    ),
                    ft.Container(
                        width=36,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        content=ft.Icon(
                            ft.Icons.FILTER_ALT_OUTLINED,
                            size=18,
                            color="#C5CDD8",
                        ),
                    ),
                    ft.Container(
                        width=36,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        content=ft.Icon(
                            ft.Icons.REFRESH,
                            size=18,
                            color="#C5CDD8",
                        ),
                    ),
                ],
            ),
        ],
    )



def _cell(width, text, color, align=ft.TextAlign.LEFT):
    return ft.Container(
        width=width,
        content=ft.Text(
            text,
            size=12,
            color=color,
            text_align=align,
            no_wrap=True,
        ),
    )


def _header():
    return ft.Container(
        padding=8,
        content=ft.Row(
            spacing=0,
            controls=[
                _cell(30, "#", "#7B8794"),
                _cell(95, "COIN", "#7B8794"),
                _cell(90, "SON FİYAT", "#7B8794"),
                _cell(60, "24H %", "#7B8794"),
                _cell(95, "24H HACİM", "#7B8794"),
                _cell(70, "SİNYAL", "#7B8794"),
                _cell(70, "DURUM", "#7B8794"),
            ],
        ),
    )


def _row(idx, coin, price, change, volume, signal, status):
    change_color = "#22C55E" if change.startswith("+") else "#EF4444"

    signal_color = {
        "BUY": "#22C55E",
        "SELL": "#EF4444",
        "WAIT": "#F59E0B",
    }[signal]

    return ft.Container(
        height=42,
        bgcolor="#131C2B",
        border_radius=8,
        padding=10,
        content=ft.Row(
            spacing=0,
            controls=[
                _cell(30, str(idx), "#C5CDD8"),
                _cell(95, coin, "white"),
                _cell(90, price, "white"),
                _cell(60, change, change_color),
                _cell(95, volume, "white"),
                _cell(70, signal, signal_color),
                _cell(70, status, "#94A3B8"),
            ],
        ),
    )

def build_coin_table():
    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border_radius=12,
        padding=15,
        content=ft.Column(
            spacing=8,
            controls=[
                _toolbar(),
                _header(),
                _row(1, "BTC/USDT", "66,812.50", "+23%", "25B", "BUY", "READY"),
                _row(2, "ETH/USDT", "3,254.08", "+2.11%", "987M", "BUY", "READY"),
                _row(3, "SOL/USDT", "159.32", "+3.45%", "456M", "BUY", "READY"),
                _row(4, "XRP/USDT", "1972", "-0.45%", "345M", "SELL", "ALERT"),
                _row(5, "DOGE/USDT", "0.1523", "+1.02%", "289M", "BUY", "READY"),
                _row(6, "ADA/USDT", "1831", "+0.76%", "234M", "BUY", "READY"),
                _row(7, "AVAX/USDT", "34.21", "+2.34%", "198M", "BUY", "READY"),
                _row(8, "DOT/USDT", "6.824", "+0.18%", "176M", "BUY", "READY"),
            ],
        ),
    )
