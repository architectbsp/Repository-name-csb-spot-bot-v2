import logging

import ccxt
import flet as ft

from app.core.bot_engine import BotEngine

from app.ui.theme import setup_page
from app.ui.components.sidebar import DASHBOARD, SETTINGS, build_sidebar
from app.ui.components.content import build_dashboard_view
from app.ui.components.settings_panel import build_settings_view


logger = logging.getLogger(__name__)


def _describe_startup_error(error: Exception) -> tuple[str, str]:
    """
    Maps a BotEngine.start() failure to a user-facing (title, message)
    pair. ccxt.AuthenticationError covers bad/missing API keys;
    ccxt.NetworkError covers DNS/connection/timeout failures talking to
    the exchange; anything else is shown generically rather than
    crashing the app silently (B25).
    """
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
    """
    Runs the blocking BotEngine.start() (exchange connect + REST market
    scan) off the Flet UI event loop (B25). Any failure is logged and
    surfaced to the user as a dialog instead of silently freezing the UI
    or crashing the background thread unnoticed.
    """
    try:
        engine.start()
    except Exception as exc:
        logger.exception("BotEngine failed to start")
        _show_startup_error_dialog(page, exc)


def _build_view(view_name: str, engine: BotEngine) -> ft.Control:
    if view_name == SETTINGS:
        return build_settings_view(engine.config, engine.settings_store)

    return build_dashboard_view()


def main(page: ft.Page):
    setup_page(page)

    engine = BotEngine()

    page.on_disconnect = lambda _: engine.stop()

    page.window.prevent_close = True

    async def on_window_event(e: ft.WindowEvent):
        logger.debug("[WINDOW] Event: %s", e.type)
        if e.type == ft.WindowEventType.CLOSE:
            logger.info("[WINDOW] Close requested")
            engine.stop()
            await page.window.destroy()

    page.window.on_event = on_window_event

    content_area = ft.Container(
        expand=True,
        content=_build_view(DASHBOARD, engine),
    )

    sidebar_area = ft.Container()

    def navigate(view_name: str) -> None:
        sidebar_area.content = build_sidebar(view_name, navigate)
        content_area.content = _build_view(view_name, engine)
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

    # engine.start() performs blocking network I/O (exchange connect +
    # initial REST market scan). Running it on the page's executor thread
    # (rather than inline here) keeps the Flet UI responsive while it
    # happens.
    page.run_thread(_start_engine_in_background, page, engine)
