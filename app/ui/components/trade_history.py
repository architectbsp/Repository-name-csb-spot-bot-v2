import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, TradeHistoryRow
from app.ui.formatting import signed_percent


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


def build_trade_history(snapshot: DashboardSnapshot | None = None):
    rows: list[TradeHistoryRow] = list(snapshot.trade_history) if snapshot else []
    count = str(len(rows))
    body = (
        [
            _row(
                r.symbol,
                "LONG",
                signed_percent(r.pnl_percent),
                r.result,
            )
            for r in rows[:8]
        ]
        if rows
        else [ft.Text("Henüz kapanmış işlem yok", color="#64748B", size=12)]
    )

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
                        ft.Text(count, color="#C5CDD8"),
                    ],
                ),
                *body,
            ],
        ),
    )
