import flet as ft


def _row(title, value, color="white"):
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(title, size=12, color="#C5CDD8"),
            ft.Text(value, size=12, color=color, weight=ft.FontWeight.BOLD),
        ],
    )


def build_report_24h():
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
                ft.Text(
                    "24 SAATLİK RAPOR",
                    color="white",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                ),
                _row("Toplam İşlem", "25"),
                _row("Kazanan", "17", "#22C55E"),
                _row("Kaybeden", "8", "#EF4444"),
                _row("Net Kâr", "+128.89 USDT", "#22C55E"),
                _row("Net Zarar", "-23.45 USDT", "#EF4444"),
                _row("Net Sonuç", "+105.44 USDT", "#22C55E"),
                ft.Divider(height=10, color="#1B2435"),
                ft.Text(
                    "Raporu Dışa Aktar (CSV)",
                    color="#4EA8FF",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
