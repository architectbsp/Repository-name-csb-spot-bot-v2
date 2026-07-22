import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.components.dashboard import build_dashboard
from app.ui.components.dashboard_cards import build_dashboard_cards
from app.ui.components.top_bar import build_top_bar


def build_dashboard_view(
    engine=None,
    page=None,
    snapshot: DashboardSnapshot | None = None,
) -> ft.Column:
    return ft.Column(
        expand=True,
        spacing=15,
        controls=[
            build_top_bar(snapshot),
            build_dashboard_cards(snapshot),
            build_dashboard(engine, page, snapshot),
        ],
    )


# Backwards-compatible alias (older call sites / imports).
build_content = build_dashboard_view
