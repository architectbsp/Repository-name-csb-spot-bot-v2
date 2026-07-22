import logging
import threading

import ccxt
import flet as ft

from app.core.bot_engine import BotEngine
from app.ui.components.content import build_dashboard_view
from app.ui.components.settings_panel import build_settings_view
from app.ui.components.sidebar import DASHBOARD, SETTINGS, build_sidebar
from app.ui.theme import setup_page


logger = logging.getLogger(__name__)

# How often the live dashboard rebuilds itself from DashboardService.
# Short enough to feel real-time for positions/watch state; long enough
# that we never REST-spam (ticker prices come from the in-memory cache
# fed by ticker.updated, not from a balance/ticker REST call every tick
# -- only quote_balance hits the exchange, and that is best-effort).
_DASHBOARD_POLL_SECONDS = 2.0


def _describe_startup_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, ccxt.AuthenticationError):
        return (
            "Kimlik Doğrulama Hatası",
            "Borsa API anahtarları geçersiz veya yetkisiz görünüyor. "
            "Lütfen .env dosyasındaki EXCHANGE_API_KEY / "
            "EXCHANGE_API_SECRET değerlerini kontrol edip uygulamayı "
            "yeniden başlatın.",
        )

    if isinstance(error, ccxt.NetworkError):
        return (
            "Bağlantı Hatası",
            "Borsaya bağlanılamadı (ağ/zaman aşımı sorunu). İnternet "
            "bağlantınızı kontrol edip uygulamayı yeniden başlatın.",
        )

    return (
        "Başlatma Hatası",
        f"Bot başlatılırken beklenmeyen bir hata oluştu: {error}",
    )


def _show_startup_error_dialog(page: ft.Page, error: Exception) -> None:
    title, message = _describe_startup_error(error)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Text(message),
        actions=[
            ft.TextButton("Tamam", on_click=lambda _: page.pop_dialog()),
        ],
    )

    page.show_dialog(dialog)
    page.update()


def _start_engine_in_background(page: ft.Page, engine: BotEngine) -> None:
    try:
        engine.start()
    except Exception as exc:
        logger.exception("BotEngine failed to start")
        _show_startup_error_dialog(page, exc)


def _build_view(
    view_name: str,
    engine: BotEngine,
    page: ft.Page,
):
    if view_name == SETTINGS:
        return build_settings_view(engine.config, engine.settings_store)

    snapshot = engine.dashboard_service.build_snapshot()
    return build_dashboard_view(engine, page, snapshot)


def main(page: ft.Page):
    setup_page(page)

    engine = BotEngine()
    stop_event = threading.Event()
    current_view = {"name": DASHBOARD}

    page.on_disconnect = lambda _: (stop_event.set(), engine.stop())

    page.window.prevent_close = True

    async def on_window_event(e: ft.WindowEvent):
        logger.debug("[WINDOW] Event: %s", e.type)
        if e.type == ft.WindowEventType.CLOSE:
            logger.info("[WINDOW] Close requested")
            stop_event.set()
            engine.stop()
            await page.window.destroy()

    page.window.on_event = on_window_event

    content_area = ft.Container(
        expand=True,
        content=_build_view(DASHBOARD, engine, page),
    )

    sidebar_area = ft.Container()

    def navigate(view_name: str) -> None:
        current_view["name"] = view_name
        sidebar_area.content = build_sidebar(view_name, navigate)
        content_area.content = _build_view(view_name, engine, page)
        sidebar_area.update()
        content_area.update()

    sidebar_area.content = build_sidebar(DASHBOARD, navigate)

    page.add(
        ft.Row(
            expand=True,
            spacing=15,
            controls=[
                sidebar_area,
                content_area,
            ],
        )
    )

    def _refresh_dashboard_loop() -> None:
        """
        Sprint 12 -- Live Dashboard poller. Runs off the Flet UI thread
        (page.run_thread). Rebuilds the dashboard view from a fresh
        DashboardSnapshot every couple of seconds while the user is on
        the Dashboard screen; Settings and other views are left alone.
        """
        while not stop_event.wait(_DASHBOARD_POLL_SECONDS):
            if current_view["name"] != DASHBOARD:
                continue

            try:
                snapshot = engine.dashboard_service.build_snapshot()
                content_area.content = build_dashboard_view(
                    engine, page, snapshot
                )
                content_area.update()
            except Exception:
                logger.exception("Live dashboard refresh failed")

    page.run_thread(_start_engine_in_background, page, engine)
    page.run_thread(_refresh_dashboard_loop)
