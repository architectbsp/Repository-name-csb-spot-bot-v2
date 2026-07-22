import flet as ft

from app.ui.components.top_bar import build_top_bar
from app.ui.components.dashboard_cards import build_dashboard_cards
from app.ui.components.dashboard import build_dashboard


def build_dashboard_view() -> ft.Column:
    return ft.Column(
        expand=True,
        spacing=15,
        controls=[
            build_top_bar(),
            build_dashboard_cards(),
            build_dashboard(),
        ],
    )


# Backwards-compatible alias (older call sites / imports).
build_content = build_dashboard_view
