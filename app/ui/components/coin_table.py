import logging

import flet as ft

from app.core.domain.dashboard import CoinRow, DashboardSnapshot
from app.ui.components.coin_chart import open_coin_chart_dialog
from app.ui.formatting import signed_percent, volume_short


logger = logging.getLogger(__name__)


def _toolbar():
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(
                "SPOT COIN LİSTESİ",
                size=18,
                weight=ft.FontWeight.BOLD,
                color="white",
            ),
            ft.Row(
                spacing=8,
                controls=[
                    ft.Container(
                        width=180,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        padding=12,
                        content=ft.Text(
                            "Coin ara...",
                            color="#6B7280",
                            size=12,
                        ),
                    ),
                    ft.Container(
                        width=36,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        content=ft.Icon(
                            ft.Icons.FILTER_ALT_OUTLINED,
                            size=18,
                            color="#C5CDD8",
                        ),
                    ),
                    ft.Container(
                        width=36,
                        height=36,
                        bgcolor="#111827",
                        border_radius=8,
                        content=ft.Icon(
                            ft.Icons.REFRESH,
                            size=18,
                            color="#C5CDD8",
                        ),
                    ),
                ],
            ),
        ],
    )


def _cell(width, text, color, align=ft.TextAlign.LEFT):
    return ft.Container(
        width=width,
        content=ft.Text(
            text,
            size=12,
            color=color,
            text_align=align,
            no_wrap=True,
        ),
    )


def _header():
    return ft.Container(
        padding=8,
        content=ft.Row(
            spacing=0,
            controls=[
                _cell(30, "#", "#7B8794"),
                _cell(95, "COIN", "#7B8794"),
                _cell(90, "SON FİYAT", "#7B8794"),
                _cell(60, "24H %", "#7B8794"),
                _cell(95, "24H HACİM", "#7B8794"),
                _cell(70, "SİNYAL", "#7B8794"),
                _cell(70, "DURUM", "#7B8794"),
            ],
        ),
    )


def _row(idx, coin, price, change, volume, signal, status, on_click=None):
    change_color = "#22C55E" if str(change).startswith("+") else "#EF4444"

    signal_color = {
        "BUY": "#22C55E",
        "SELL": "#EF4444",
        "WAIT": "#F59E0B",
        "HOLD": "#3B82F6",
    }.get(signal, "#94A3B8")

    return ft.Container(
        height=42,
        bgcolor="#131C2B",
        border_radius=8,
        padding=10,
        ink=on_click is not None,
        on_click=on_click,
        content=ft.Row(
            spacing=0,
            controls=[
                _cell(30, str(idx), "#C5CDD8"),
                _cell(95, coin, "white"),
                _cell(90, price, "white"),
                _cell(60, change, change_color),
                _cell(95, volume, "white"),
                _cell(70, signal, signal_color),
                _cell(70, status, "#94A3B8"),
            ],
        ),
    )


def _open_chart(engine, page, symbol, exchange_name: str | None = None) -> None:
    if engine is None or page is None:
        return

    from app.core.exchange.market_key import try_parse_exchange_type

    exchange_type = try_parse_exchange_type(exchange_name)
    if exchange_type is None:
        try:
            exchange_type = engine.exchange.active_exchange_type()
        except Exception:
            logger.exception(
                "No active exchange -- cannot open chart for %s", symbol
            )
            return

    open_coin_chart_dialog(page, engine.chart_service, symbol, exchange_type)


def build_coin_table(
    engine=None,
    page=None,
    snapshot: DashboardSnapshot | None = None,
):
    coins: list[CoinRow] = list(snapshot.coins) if snapshot else []

    if coins:
        row_controls = [
            _row(
                idx,
                (
                    f"{coin.symbol} ({coin.exchange})"
                    if coin.exchange
                    else coin.symbol
                ),
                coin.price_display,
                signed_percent(coin.change_24h_percent),
                volume_short(coin.volume_24h),
                coin.signal,
                coin.status,
                on_click=(
                    (
                        lambda _,
                        symbol=coin.symbol,
                        exchange=coin.exchange: _open_chart(
                            engine, page, symbol, exchange
                        )
                    )
                    if engine is not None and page is not None
                    else None
                ),
            )
            for idx, coin in enumerate(coins[:20], start=1)
        ]
    else:
        row_controls = [
            ft.Text(
                "Henüz izlenen coin yok — scanner çalışınca dolacak.",
                color="#64748B",
                size=12,
            )
        ]

    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border_radius=12,
        padding=15,
        content=ft.Column(
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                _toolbar(),
                _header(),
                *row_controls,
            ],
        ),
    )
