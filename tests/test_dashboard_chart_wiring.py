"""
Sprint 12 -- Live Dashboard chart wiring: clicking a live coin row or
open-position card opens the coin chart dialog. Rows come from a
DashboardSnapshot (no more static mock data).
"""

from datetime import UTC, datetime

import app.ui.components.coin_table as coin_table
import app.ui.components.open_positions as open_positions
from app.core.domain.dashboard import (
    CoinRow,
    DashboardSnapshot,
    OpenPositionRow,
)


class DummyExchangeManager:
    def __init__(self, exchange_type="BINANCE", raise_error=False):
        self._exchange_type = exchange_type
        self._raise_error = raise_error

    def active_exchange_type(self):
        if self._raise_error:
            raise RuntimeError("No enabled exchange is registered.")
        return self._exchange_type


class DummyEngine:
    def __init__(self, raise_error=False):
        self.exchange = DummyExchangeManager(raise_error=raise_error)
        self.chart_service = object()


class DummyPage:
    pass


def make_snapshot() -> DashboardSnapshot:
    return DashboardSnapshot(
        generated_at=datetime.now(UTC),
        coins=[
            CoinRow(
                symbol="BTC/USDT",
                price_display="66000",
                change_24h_percent=1.5,
                volume_24h=1e9,
                signal="WAIT",
                status="WATCH_RISING",
            )
        ],
        open_positions=[
            OpenPositionRow(
                symbol="BTCUSDT",
                entry_price=100.0,
                current_price=105.0,
                pnl_percent=5.0,
                stop_stage="HARD",
                quantity=1.0,
            )
        ],
    )


def _find_first_row_click_handler(control):
    for row in control.content.controls[2:]:
        if getattr(row, "on_click", None) is not None:
            return row

    raise AssertionError("No row with an on_click handler was found")


def test_coin_table_rows_have_no_click_handler_without_a_live_engine():
    table = coin_table.build_coin_table(snapshot=make_snapshot())

    rows = [
        c for c in table.content.controls[2:] if hasattr(c, "on_click")
    ]
    assert rows
    assert all(row.on_click is None for row in rows)


def test_clicking_a_coin_table_row_opens_the_chart_dialog(monkeypatch):
    captured = {}

    def fake_open_dialog(page, chart_service, symbol, exchange_type):
        captured["page"] = page
        captured["chart_service"] = chart_service
        captured["symbol"] = symbol
        captured["exchange_type"] = exchange_type

    monkeypatch.setattr(coin_table, "open_coin_chart_dialog", fake_open_dialog)

    engine = DummyEngine()
    page = DummyPage()
    table = coin_table.build_coin_table(engine, page, make_snapshot())

    row = _find_first_row_click_handler(table)
    row.on_click(None)

    assert captured["page"] is page
    assert captured["chart_service"] is engine.chart_service
    assert captured["symbol"] == "BTC/USDT"
    assert captured["exchange_type"] == "BINANCE"


def test_clicking_a_coin_table_row_is_a_no_op_when_no_exchange_is_active(monkeypatch):
    calls = []
    monkeypatch.setattr(
        coin_table,
        "open_coin_chart_dialog",
        lambda *a, **kw: calls.append((a, kw)),
    )

    engine = DummyEngine(raise_error=True)
    page = DummyPage()
    table = coin_table.build_coin_table(engine, page, make_snapshot())

    row = _find_first_row_click_handler(table)
    row.on_click(None)

    assert calls == []


def test_open_positions_cards_have_no_click_handler_without_a_live_engine():
    panel = open_positions.build_open_positions(snapshot=make_snapshot())

    cards = [
        c for c in panel.content.controls[1:] if hasattr(c, "on_click")
    ]
    assert cards
    assert all(card.on_click is None for card in cards)


def test_clicking_an_open_position_card_opens_the_chart_dialog(monkeypatch):
    captured = {}

    def fake_open_dialog(page, chart_service, symbol, exchange_type):
        captured["symbol"] = symbol
        captured["exchange_type"] = exchange_type

    monkeypatch.setattr(open_positions, "open_coin_chart_dialog", fake_open_dialog)

    engine = DummyEngine()
    page = DummyPage()
    panel = open_positions.build_open_positions(engine, page, make_snapshot())

    card = panel.content.controls[1]
    card.on_click(None)

    assert captured["symbol"] == "BTCUSDT"
    assert captured["exchange_type"] == "BINANCE"
