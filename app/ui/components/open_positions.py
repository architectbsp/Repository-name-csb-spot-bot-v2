import logging

import flet as ft

from app.ui.components.coin_chart import open_coin_chart_dialog


logger = logging.getLogger(__name__)


def _badge(text, color):
    return ft.Container(
        bgcolor=color,
        border_radius=20,
        padding=6,
        content=ft.Text(
            text,
            size=10,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF",
        ),
    )


def _position(symbol, side, entry, current, pnl, on_click=None):
    pnl_color = "#22C55E" if pnl.startswith("+") else "#EF4444"
    side_color = "#22C55E" if side == "LONG" else "#EF4444"

    return ft.Container(
        bgcolor="#111827",
        border_radius=10,
        padding=12,
        ink=on_click is not None,
        on_click=on_click,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(symbol, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                        _badge(side, side_color),
                    ],
                ),
                ft.Column(
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                    controls=[
                        ft.Text(f"Entry : {entry}", size=11, color="#94A3B8"),
                        ft.Text(f"Now : {current}", size=11, color="#94A3B8"),
                        ft.Text(
                            pnl,
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=pnl_color,
                        ),
                    ],
                ),
            ],
        ),
    )


def _open_chart(engine, page, symbol) -> None:
    """Sprint 6 -- "coin'e tıklayınca grafik göster". Silently no-ops
    without a live `engine`/`page` (headless/tests, or before BotEngine
    finishes connecting)."""
    if engine is None or page is None:
        return

    try:
        exchange_type = engine.exchange.active_exchange_type()
    except Exception:
        logger.exception("No active exchange -- cannot open chart for %s", symbol)
        return

    open_coin_chart_dialog(page, engine.chart_service, symbol, exchange_type)


def build_open_positions(engine=None, page=None):
    positions = [
        ("BTCUSDT", "LONG", "118100", "118420", "+0.27%"),
        ("ETHUSDT", "SHORT", "3940", "3920", "+0.51%"),
        ("SOLUSDT", "LONG", "180", "184", "+2.22%"),
    ]

    handler_factory = (
        (lambda symbol: (lambda _: _open_chart(engine, page, symbol)))
        if engine is not None and page is not None
        else (lambda symbol: None)
    )

    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border_radius=14,
        padding=18,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Text(
                    "OPEN POSITIONS",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                ),
                *(
                    _position(*position, on_click=handler_factory(position[0]))
                    for position in positions
                ),
            ],
        ),
    )
