"""
Sprint 6 -- Coin charts: build_coin_chart() is pure rendering (ChartData
in, a Control tree out) so it's fully testable headlessly, without a
running Flet Page -- see tests/test_settings_panel.py for the same
pattern used elsewhere in this project.
"""

from datetime import UTC, datetime

import flet as ft
import flet.canvas as canvas

from app.core.domain.candle import Candle
from app.core.domain.chart import STATUS_CLOSED, STATUS_OPEN, ChartData
from app.ui.components.coin_chart import build_coin_chart


def make_candles(count=10):
    return [
        Candle(
            timestamp=i * 60_000,
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100 + i,
            volume=1.0,
        )
        for i in range(count)
    ]


def _canvas_of(control) -> canvas.Canvas:
    # build_coin_chart returns Container(content=Column(controls=[header_row, Canvas]))
    for child in control.content.controls:
        if isinstance(child, canvas.Canvas):
            return child

    raise AssertionError("No Canvas found in the chart control tree")


def test_build_coin_chart_shows_a_friendly_empty_state_with_no_candles():
    chart_data = ChartData(symbol="DOGEUSDT")

    control = build_coin_chart(chart_data)

    assert isinstance(control, ft.Container)
    # No canvas.Canvas anywhere -- just a "no data" message.
    assert not any(
        isinstance(c, canvas.Canvas) for c in _walk(control)
    )


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)


def test_build_coin_chart_draws_the_price_line_and_all_overlay_levels():
    chart_data = ChartData(
        symbol="BTCUSDT",
        candles=make_candles(),
        status=STATUS_OPEN,
        entry_price=103.0,
        entry_time=datetime.fromtimestamp(3 * 60, UTC),
        stop_price=98.0,
        stop_stage="TRAILING",
        take_profit_price=106.0,
        trailing_reference_price=108.0,
    )

    control = build_coin_chart(chart_data)
    chart_canvas = _canvas_of(control)

    points_shapes = [s for s in chart_canvas.shapes if isinstance(s, canvas.Points)]
    line_shapes = [s for s in chart_canvas.shapes if isinstance(s, canvas.Line)]
    text_shapes = [s for s in chart_canvas.shapes if isinstance(s, canvas.Text)]
    circle_shapes = [s for s in chart_canvas.shapes if isinstance(s, canvas.Circle)]

    # One continuous price polyline.
    assert len(points_shapes) == 1
    assert len(points_shapes[0].points) == len(chart_data.candles)

    # Entry / Stop / Take-Profit / Trailing -- 4 horizontal level lines + labels.
    assert len(line_shapes) == 4
    assert len(text_shapes) == 4

    # Entry marker circle (no exit yet -- still an open position).
    assert len(circle_shapes) == 1


def test_build_coin_chart_marks_the_exit_point_for_a_closed_trade():
    chart_data = ChartData(
        symbol="ETHUSDT",
        candles=make_candles(),
        status=STATUS_CLOSED,
        entry_price=100.0,
        entry_time=datetime.fromtimestamp(1 * 60, UTC),
        exit_price=95.0,
        exit_time=datetime.fromtimestamp(8 * 60, UTC),
        exit_reason="HARD_STOP",
    )

    control = build_coin_chart(chart_data)
    chart_canvas = _canvas_of(control)

    circle_shapes = [s for s in chart_canvas.shapes if isinstance(s, canvas.Circle)]

    # Entry marker + Exit marker.
    assert len(circle_shapes) == 2


def test_build_coin_chart_renders_without_any_overlay_when_symbol_has_no_trade():
    chart_data = ChartData(symbol="ADAUSDT", candles=make_candles())

    control = build_coin_chart(chart_data)
    chart_canvas = _canvas_of(control)

    # Just the price line -- no Entry/Stop/TP/Trailing levels or markers.
    assert len(chart_canvas.shapes) == 1
    assert isinstance(chart_canvas.shapes[0], canvas.Points)
