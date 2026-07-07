import flet as ft

from app.core.bot_engine import BotEngine

from app.ui.theme import setup_page
from app.ui.components.sidebar import build_sidebar
from app.ui.components.content import build_content


def main(page: ft.Page):
    setup_page(page)

    engine = BotEngine()
    engine.start()

    page.on_disconnect = lambda _: engine.stop()

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
