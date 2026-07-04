import flet as ft


def _log(time, level, text):
    colors = {
        "INFO": "#3B82F6",
        "TRADE": "#22C55E",
        "WARNING": "#F59E0B",
        "ERROR": "#EF4444",
        "API": "#06B6D4",
    }

    return ft.Row(
        spacing=10,
        controls=[
            ft.Text(time, width=60, size=11, color="#94A3B8"),
            ft.Text(
                level,
                width=55,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=colors.get(level, "#FFFFFF"),
            ),
            ft.Text(text, expand=True, size=12, color="white"),
        ],
    )


def build_bot_log():
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
            spacing=10,
            controls=[
                ft.Text(
                    "CANLI LOG",
                    color="white",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                ),
                _log("10:15:30", "INFO", "İnternet bağlantısı kontrol edildi: Bağlı"),
                _log("10:15:25", "TRADE", "BTC/USDT - Trailing stop güncellendi"),
                _log("10:15:20", "INFO", "Piyasa verileri güncellendi"),
                _log("10:15:15", "TRADE", "SOL/USDT giriş sinyali algılandı"),
                _log("10:15:10", "API", "Bybit ticker verileri alındı"),
                _log("10:15:05", "TRADE", "ETH/USDT take profit gerçekleşti"),
                _log("10:15:00", "INFO", "Bot döngüsü tamamlandı"),
            ],
        ),
    )
