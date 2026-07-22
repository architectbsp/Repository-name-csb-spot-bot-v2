import logging

import flet as ft

from app.core.domain.dashboard import DashboardSnapshot, OpenPositionRow
from app.ui.components.coin_chart import open_coin_chart_dialog
from app.ui.formatting import signed_percent


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


def _position(symbol, side, entry, current, pnl, stage, on_click=None):
    pnl_color = (
        "#22C55E"
        if str(pnl).startswith("+")
        else ("#EF4444" if str(pnl).startswith("-") else "#94A3B8")
    )
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
                        ft.Row(
                            spacing=6,
                            controls=[
                                _badge(side, side_color),
                                _badge(stage, "#3B82F6"),
                            ],
                        ),
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


def _emergency_exit(engine, page) -> None:
    if engine is None or page is None:
        return

    def _confirm(_):
        try:
            closed = engine.risk_manager.emergency_exit_all()
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"Emergency Exit: {closed} pozisyon kapatıldı"),
            )
        except Exception:
            logger.exception("Emergency Exit failed")
            page.snack_bar = ft.SnackBar(
                content=ft.Text("Emergency Exit başarısız — loglara bakın"),
            )
        page.snack_bar.open = True
        dialog.open = False
        page.update()

    def _cancel(_):
        dialog.open = False
        page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Emergency Exit"),
        content=ft.Text(
            "Tüm açık pozisyonlar pazar emriyle kapatılacak. Emin misiniz?"
        ),
        actions=[
            ft.TextButton("İptal", on_click=_cancel),
            ft.TextButton(
                "Kapat",
                on_click=_confirm,
                style=ft.ButtonStyle(color="#EF4444"),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def build_open_positions(
    engine=None,
    page=None,
    snapshot: DashboardSnapshot | None = None,
):
    positions: list[OpenPositionRow] = (
        list(snapshot.open_positions) if snapshot else []
    )

    handler_factory = (
        (
            lambda symbol, exchange: (
                lambda _: _open_chart(engine, page, symbol, exchange)
            )
        )
        if engine is not None and page is not None
        else (lambda symbol, exchange: None)
    )

    if positions:
        cards = [
            _position(
                f"{p.symbol} ({p.exchange})" if p.exchange else p.symbol,
                "LONG",
                f"{p.entry_price:g}",
                f"{p.current_price:g}" if p.current_price is not None else "-",
                signed_percent(p.pnl_percent),
                p.stop_stage,
                on_click=handler_factory(p.symbol, p.exchange),
            )
            for p in positions
        ]
    else:
        cards = [
            ft.Text("Açık pozisyon yok", color="#64748B", size=12),
        ]

    header = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(
                "OPEN POSITIONS",
                size=18,
                weight=ft.FontWeight.BOLD,
                color="#FFFFFF",
            ),
            ft.OutlinedButton(
                "Emergency Exit",
                icon=ft.Icons.WARNING_AMBER,
                style=ft.ButtonStyle(color="#EF4444"),
                disabled=engine is None or page is None or not positions,
                on_click=(
                    (lambda _: _emergency_exit(engine, page))
                    if engine is not None and page is not None
                    else None
                ),
            ),
        ],
    )

    return ft.Container(
        expand=True,
        bgcolor="#0B1220",
        border_radius=14,
        padding=18,
        content=ft.Column(
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                header,
                *cards,
            ],
        ),
    )
