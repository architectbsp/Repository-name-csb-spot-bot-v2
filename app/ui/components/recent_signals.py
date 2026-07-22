import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, WatchRow


def _row(symbol, direction, change, status):
    color = "#22C55E" if direction == "RISE" else "#F59E0B"

    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(symbol, color="white", size=12, expand=2),
            ft.Text(direction, color=color, size=12, expand=1),
            ft.Text(change, color=color, size=12, expand=1),
            ft.Text(status, color="#F59E0B", size=12, expand=2),
        ],
    )


def _empty():
    return ft.Text(
        "İzlenen coin yok",
        color="#64748B",
        size=12,
    )


def build_recent_signals(snapshot: DashboardSnapshot | None = None):
    rows: list[WatchRow] = list(snapshot.watch_list) if snapshot else []
    count = str(len(rows))
    body = (
        [_row(r.symbol, r.direction, r.change_display, r.status) for r in rows[:8]]
        if rows
        else [_empty()]
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
                            "WATCH LIST",
                            color="white",
                            weight=ft.FontWeight.BOLD,
                            size=15,
                        ),
                        ft.Text(count, color="#C5CDD8"),
                    ],
                ),
                *body,
            ],
        ),
    )
