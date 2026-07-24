import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.components.dashboard import build_dashboard
from app.ui.components.dashboard_cards import build_dashboard_cards
from app.ui.components.top_bar import build_top_bar


def build_dashboard_view(
    engine=None,
    page=None,
    snapshot: DashboardSnapshot | None = None,
    on_top_action=None,
    on_exchange_select=None,
    coin_search_query: str = "",
    on_coin_search=None,
    on_coin_refresh=None,
) -> ft.Column:
    return ft.Column(
        expand=True,
        spacing=15,
        controls=[
            build_top_bar(
                snapshot,
                on_action=on_top_action,
                on_exchange_select=on_exchange_select,
            ),
            build_dashboard_cards(snapshot),
            build_dashboard(
                engine,
                page,
                snapshot,
                coin_search_query=coin_search_query,
                on_coin_search=on_coin_search,
                on_coin_refresh=on_coin_refresh,
            ),
        ],
    )


# Backwards-compatible alias (older call sites / imports).
build_content = build_dashboard_view
