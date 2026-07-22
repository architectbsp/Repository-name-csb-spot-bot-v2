import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, Report24h
from app.ui.formatting import money, signed_money


def _row(title, value, color="white"):
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(title, size=12, color="#C5CDD8"),
            ft.Text(value, size=12, color=color, weight=ft.FontWeight.BOLD),
        ],
    )


def build_report_24h(snapshot: DashboardSnapshot | None = None):
    report: Report24h = snapshot.report_24h if snapshot else Report24h()
    net_color = "#22C55E" if report.net_pnl >= 0 else "#EF4444"

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
                _row("Toplam İşlem", str(report.total_trades)),
                _row("Kazanan", str(report.winning_trades), "#22C55E"),
                _row("Kaybeden", str(report.losing_trades), "#EF4444"),
                _row(
                    "Net Kâr",
                    money(report.gross_profit),
                    "#22C55E",
                ),
                _row(
                    "Net Zarar",
                    money(report.gross_loss),
                    "#EF4444",
                ),
                _row(
                    "Net Sonuç",
                    signed_money(report.net_pnl),
                    net_color,
                ),
            ],
        ),
    )
