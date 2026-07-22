import math

import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, Report24h
from app.core.domain.performance import PerformanceReport
from app.ui.formatting import money, signed_money


def _row(title, value, color="white"):
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(title, size=12, color="#C5CDD8"),
            ft.Text(value, size=12, color=color, weight=ft.FontWeight.BOLD),
        ],
    )


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    if math.isinf(value):
        return "∞"
    return f"{value:.2f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _performance_rows(report: PerformanceReport | None) -> list:
    if report is None or report.total_trades == 0:
        return [
            ft.Text(
                "PERFORMANS (TÜM ZAMANLAR)",
                color="white",
                size=13,
                weight=ft.FontWeight.BOLD,
            ),
            _row("Win Rate", "-"),
            _row("Expectancy", "-"),
            _row("Profit Factor", "-"),
            _row("Sharpe", "-"),
            _row("Max Drawdown", "-"),
        ]

    return [
        ft.Text(
            "PERFORMANS (TÜM ZAMANLAR)",
            color="white",
            size=13,
            weight=ft.FontWeight.BOLD,
        ),
        _row("Total PnL", money(report.total_pnl)),
        _row("Win Rate", _fmt_pct(report.win_rate_percent), "#38BDF8"),
        _row("Avg Profit", money(report.average_profit), "#22C55E"),
        _row("Avg Loss", money(report.average_loss), "#EF4444"),
        _row("Profit Factor", _fmt_ratio(report.profit_factor)),
        _row("Sharpe", _fmt_ratio(report.sharpe_ratio)),
        _row("Max Drawdown", money(report.max_drawdown), "#F59E0B"),
        _row("Expectancy", money(report.expectancy)),
    ]


def build_report_24h(snapshot: DashboardSnapshot | None = None):
    report: Report24h = snapshot.report_24h if snapshot else Report24h()
    performance = snapshot.performance if snapshot else None
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
            scroll=ft.ScrollMode.AUTO,
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
                ft.Divider(height=12, color="#1B2435"),
                *_performance_rows(performance),
            ],
        ),
    )
