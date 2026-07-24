"""TASK-02 — exchange selection / active venue switching."""

from __future__ import annotations

from datetime import UTC, datetime

import flet as ft

from app.core.config.settings import ExchangeSettings
from app.core.domain.dashboard import DashboardSnapshot
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.ui.components.top_bar import build_top_bar, _resolve_active_exchange


def _register(registry: ExchangeRegistry, exchange_type: ExchangeType) -> None:
    registry.register(
        exchange_type,
        BinanceExchange(
            ExchangeState(exchange=exchange_type, enabled=True),
            ExchangeSettings(exchange=exchange_type.name.lower()),
        ),
    )


def test_set_active_exchange_updates_manager_selection():
    registry = ExchangeRegistry()
    _register(registry, ExchangeType.BINANCE)
    _register(registry, ExchangeType.BYBIT)
    manager = ExchangeManager(registry)

    assert manager.active_exchange_type() == ExchangeType.BINANCE

    manager.set_active_exchange_type(ExchangeType.BYBIT)
    assert manager.selected_exchange_type() == ExchangeType.BYBIT
    assert manager.active_exchange_type() == ExchangeType.BYBIT

    manager.set_active_exchange_type(ExchangeType.OKX)
    # OKX not registered — preference stored, active falls back to enabled.
    assert manager.selected_exchange_type() == ExchangeType.OKX
    assert manager.active_exchange_type() == ExchangeType.BINANCE


def test_top_bar_exchange_chips_are_clickable_and_highlight_active():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        exchange_name="BINANCE,BYBIT",
        enabled_exchanges=["BINANCE", "BYBIT"],
        active_exchange="BYBIT",
        bot_running=True,
        api_connected=True,
    )
    clicks: list[str] = []
    bar = build_top_bar(snap, on_exchange_select=clicks.append)

    chips = [
        c
        for c in _walk(bar)
        if isinstance(c, ft.Container)
        and isinstance(getattr(c, "content", None), ft.Text)
        and c.content.value in {"BINANCE", "BYBIT", "OKX", "KRAKEN", "MEXC"}
    ]
    assert len(chips) == 5
    bybit = next(c for c in chips if c.content.value == "BYBIT")
    binance = next(c for c in chips if c.content.value == "BINANCE")
    assert bybit.bgcolor == "#2563EB"
    assert binance.bgcolor == "#0B1220"
    assert bybit.on_click is not None
    bybit.on_click(None)
    assert clicks == ["BYBIT"]


def test_resolve_active_exchange_prefers_active_field():
    snap = DashboardSnapshot(
        generated_at=datetime.now(UTC),
        exchange_name="BINANCE,OKX",
        enabled_exchanges=["BINANCE", "OKX"],
        active_exchange="OKX",
    )
    assert _resolve_active_exchange(snap) == "OKX"


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
