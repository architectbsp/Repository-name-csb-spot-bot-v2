import flet as ft

from app.core.domain.dashboard import CooldownRow, DashboardSnapshot
from app.ui.formatting import duration_hms, hhmmss


def _row(symbol, stop_time, remaining):
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(symbol, color="white", size=12, expand=2),
            ft.Text(stop_time, color="#C5CDD8", size=12, expand=2),
            ft.Text(remaining, color="#22C55E", size=12, expand=1),
        ],
    )


def build_cooldown(snapshot: DashboardSnapshot | None = None):
    rows: list[CooldownRow] = list(snapshot.cooldowns) if snapshot else []
    count = str(len(rows))
    body = (
        [
            _row(
                r.symbol,
                hhmmss(r.cooldown_until),
                duration_hms(r.remaining_seconds),
            )
            for r in rows[:8]
        ]
        if rows
        else [ft.Text("Cooldown yok", color="#64748B", size=12)]
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
                            "COOLDOWN",
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
