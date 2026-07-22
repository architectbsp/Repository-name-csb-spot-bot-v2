import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, LogRow


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
            ft.Text(text, expand=True, size=12, color="white", no_wrap=True),
        ],
    )


def build_bot_log(snapshot: DashboardSnapshot | None = None):
    rows: list[LogRow] = list(snapshot.logs) if snapshot else []
    # Newest at the bottom of the ring buffer -- show newest last (tail).
    body = (
        [_log(r.time_display, r.level, r.message) for r in rows[-12:]]
        if rows
        else [ft.Text("Henüz log yok", color="#64748B", size=12)]
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
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "CANLI LOG",
                    color="white",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                ),
                *body,
            ],
        ),
    )
