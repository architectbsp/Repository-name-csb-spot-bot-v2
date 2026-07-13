import logging
import flet as ft

from app.core.bot_engine import BotEngine

from app.ui.theme import setup_page
from app.ui.components.sidebar import build_sidebar
from app.ui.components.content import build_content


logger = logging.getLogger(__name__)


def main(page: ft.Page):
    setup_page(page)

    engine = BotEngine()
    engine.start()

    page.on_disconnect = lambda _: engine.stop()

    page.window.prevent_close = True

    async def on_window_event(e: ft.WindowEvent):
        logger.debug("[WINDOW] Event: %s", e.type)
        if e.type == ft.WindowEventType.CLOSE:
            logger.info("[WINDOW] Close requested")
            engine.stop()
            await page.window.destroy()

    page.window.on_event = on_window_event

    page.add(
        ft.Row(
            expand=True,
            spacing=15,
            controls=[
                build_sidebar(),
                ft.Container(
                    expand=True,
                    content=build_content(),
                ),
            ],
        )
    )
