"""
Coin charts: TradingView-like price chart on flet.canvas (no Plotly /
lightweight-charts dependency -- BUSINESS_RULES §10/B29). Renders the
price line plus dynamic Entry / Stop Loss / TP / Trailing Stop overlays
from ChartService.ChartData.

build_coin_chart() is pure/unit-testable. open_coin_chart_dialog() shows
a modal that auto-refreshes overlays + candles while open.
"""

from __future__ import annotations

import logging
import threading
import time

import flet as ft
import flet.canvas as canvas

from app.core.domain.chart import STATUS_CLOSED, STATUS_OPEN, ChartData
from app.core.services.chart_service import ChartService
from app.ui.theme import BORDER, DANGER, SUCCESS, SURFACE, TEXT, TEXT_SECONDARY


logger = logging.getLogger(__name__)

_WIDTH = 640
_HEIGHT = 300
_PADDING = 24
_LIVE_REFRESH_SECONDS = 5.0

_ENTRY_COLOR = "#FACC15"
_STOP_COLOR = DANGER
_TARGET_COLOR = SUCCESS
_TRAILING_COLOR = "#A855F7"
_PRICE_LINE_COLOR = "#38BDF8"


def _nearest_index(candles: list, epoch_ms: float) -> int:
    """Index of the candle whose timestamp is closest to `epoch_ms`,
    clamped to the candle range (used to place Entry/Exit markers on the
    x-axis even if the requested timeframe/limit doesn't reach that far
    back or forward)."""
    if not candles:
        return 0

    best_index = 0
    best_diff = abs(candles[0].timestamp - epoch_ms)

    for index, candle in enumerate(candles):
        diff = abs(candle.timestamp - epoch_ms)
        if diff < best_diff:
            best_index = index
            best_diff = diff

    return best_index


def _empty_chart(symbol: str) -> ft.Control:
    return ft.Container(
        width=_WIDTH,
        height=_HEIGHT,
        bgcolor=SURFACE,
        border_radius=12,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(symbol, color=TEXT, weight=ft.FontWeight.BOLD, size=16),
                ft.Text(
                    "Bu sembol için henüz grafik verisi yok.",
                    color=TEXT_SECONDARY,
                    size=12,
                ),
            ],
        ),
    )


def build_coin_chart(chart_data: ChartData) -> ft.Control:
    candles = chart_data.candles

    if not candles:
        return _empty_chart(chart_data.symbol)

    closes = [candle.close for candle in candles]
    overlay_levels = [
        price
        for price in (
            chart_data.entry_price,
            chart_data.stop_price,
            chart_data.take_profit_price,
            chart_data.trailing_reference_price,
            chart_data.exit_price,
        )
        if price is not None
    ]

    min_price = min(closes + overlay_levels)
    max_price = max(closes + overlay_levels)
    price_range = (max_price - min_price) or (max_price or 1.0) * 0.01 or 1.0

    plot_width = _WIDTH - 2 * _PADDING
    plot_height = _HEIGHT - 2 * _PADDING
    last_index = len(candles) - 1

    def x_for(index: int) -> float:
        if last_index == 0:
            return float(_PADDING)
        return _PADDING + (index / last_index) * plot_width

    def y_for(price: float) -> float:
        return _PADDING + (1 - (price - min_price) / price_range) * plot_height

    shapes: list[canvas.Shape] = [
        canvas.Points(
            points=[(x_for(i), y_for(close)) for i, close in enumerate(closes)],
            point_mode=canvas.PointMode.POLYGON,
            paint=ft.Paint(
                color=_PRICE_LINE_COLOR,
                stroke_width=2,
                style=ft.PaintingStyle.STROKE,
            ),
        )
    ]

    def add_level(price: float | None, color: str, label: str) -> None:
        if price is None:
            return

        y = y_for(price)
        shapes.append(
            canvas.Line(
                _PADDING,
                y,
                _WIDTH - _PADDING,
                y,
                paint=ft.Paint(
                    color=color,
                    stroke_width=1,
                    stroke_dash_pattern=[6, 4],
                ),
            )
        )
        shapes.append(
            canvas.Text(
                _PADDING + 4,
                max(y - 14, 2),
                f"{label} {price:g}",
                style=ft.TextStyle(color=color, size=10, weight=ft.FontWeight.BOLD),
            )
        )

    add_level(chart_data.entry_price, _ENTRY_COLOR, "ENTRY")
    add_level(chart_data.stop_price, _STOP_COLOR, "STOP LOSS")
    add_level(chart_data.take_profit_price, _TARGET_COLOR, "TP")
    add_level(
        chart_data.trailing_reference_price,
        _TRAILING_COLOR,
        "TRAILING STOP",
    )

    if chart_data.entry_time is not None:
        entry_index = _nearest_index(candles, chart_data.entry_time.timestamp() * 1000)
        shapes.append(
            canvas.Circle(
                x_for(entry_index),
                y_for(chart_data.entry_price or closes[entry_index]),
                radius=5,
                paint=ft.Paint(color=_ENTRY_COLOR, style=ft.PaintingStyle.FILL),
            )
        )

    if chart_data.exit_price is not None and chart_data.exit_time is not None:
        exit_index = _nearest_index(candles, chart_data.exit_time.timestamp() * 1000)
        exit_color = (
            SUCCESS
            if (chart_data.exit_price >= (chart_data.entry_price or 0))
            else DANGER
        )
        shapes.append(
            canvas.Circle(
                x_for(exit_index),
                y_for(chart_data.exit_price),
                radius=5,
                paint=ft.Paint(color=exit_color, style=ft.PaintingStyle.FILL),
            )
        )

    status_label = {
        STATUS_OPEN: ("AÇIK POZİSYON", SUCCESS),
        STATUS_CLOSED: (
            f"KAPANDI ({chart_data.exit_reason or '-'})",
            TEXT_SECONDARY,
        ),
    }.get(chart_data.status or "", ("", TEXT_SECONDARY))

    return ft.Container(
        width=_WIDTH,
        bgcolor=SURFACE,
        border=ft.Border(
            left=ft.BorderSide(1, BORDER),
            right=ft.BorderSide(1, BORDER),
            top=ft.BorderSide(1, BORDER),
            bottom=ft.BorderSide(1, BORDER),
        ),
        border_radius=12,
        padding=12,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            chart_data.symbol,
                            color=TEXT,
                            weight=ft.FontWeight.BOLD,
                            size=16,
                        ),
                        ft.Text(
                            status_label[0],
                            color=status_label[1],
                            size=12,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                ),
                canvas.Canvas(
                    shapes=shapes,
                    width=_WIDTH,
                    height=_HEIGHT,
                ),
            ],
        ),
    )


def open_coin_chart_dialog(
    page: ft.Page,
    chart_service: ChartService,
    symbol: str,
    exchange_type,
) -> None:
    """
    Click-a-coin live chart: fetches ChartData, shows Entry/SL/TP/Trailing
    overlays, and refreshes every few seconds while the dialog stays open
    so stop/trailing lines track the live position.
    """

    def _load() -> ChartData:
        try:
            return chart_service.build_chart_data(symbol, exchange_type)
        except Exception:
            logger.exception("Failed to build chart data for %s", symbol)
            return ChartData(symbol=symbol)

    chart_host = ft.Column(
        tight=True,
        controls=[build_coin_chart(_load())],
    )
    state = {"alive": True}

    def _rebuild(_: object | None = None) -> None:
        chart_host.controls = [build_coin_chart(_load())]
        try:
            page.update()
        except Exception:
            state["alive"] = False

    def _close(_: object | None = None) -> None:
        state["alive"] = False
        page.pop_dialog()

    def _auto_refresh() -> None:
        while state["alive"]:
            time.sleep(_LIVE_REFRESH_SECONDS)
            if not state["alive"]:
                break
            try:
                _rebuild()
            except Exception:
                logger.exception("Live chart refresh failed for %s", symbol)
                break

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"{symbol} Grafiği (canlı)", color=TEXT),
        content=chart_host,
        actions=[
            ft.TextButton("Yenile", on_click=_rebuild),
            ft.TextButton("Kapat", on_click=_close),
        ],
    )

    page.show_dialog(dialog)
    page.update()
    threading.Thread(target=_auto_refresh, daemon=True).start()
