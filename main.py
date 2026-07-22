import flet as ft

from app.core.logging_config import configure_logging

configure_logging()

from app.ui.app import main  # noqa: E402 - logging must be configured first

ft.run(main)
