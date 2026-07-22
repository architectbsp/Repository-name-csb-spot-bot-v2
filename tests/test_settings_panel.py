"""
Sprint 1 Settings screen: verifies the Save button actually drives
SettingsStore.update() (persist + live in-place mutation of the shared
AppSettings instance), independent of Flet's page-attached UI refresh
(which requires a real running Page and isn't exercised by these
headless unit tests).
"""

import flet as ft
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config.settings import AppSettings
from app.core.config.settings_store import SettingsStore
from app.core.persistence.database import Base
from app.core.persistence.repository import SettingsRepository
from app.ui.components.settings_panel import build_settings_view


def make_store() -> SettingsStore:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, future=True)()
    return SettingsStore(SettingsRepository(session))


def _walk(control):
    yield control

    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)

    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)


def _collect(view):
    button = None
    fields_by_label = {}

    for control in _walk(view):
        if isinstance(control, ft.Button):
            button = control
        if isinstance(control, ft.TextField):
            fields_by_label[control.label] = control

    return button, fields_by_label


def _click_save(button) -> None:
    """Flet's Control.update() raises when the control tree isn't
    attached to a real running Page, which is expected in headless unit
    tests; the settings mutation/persistence itself already happened
    before that point in _on_save, so it's safe to swallow here."""
    try:
        button.on_click(None)
    except RuntimeError as exc:
        assert "must be added to the page" in str(exc)


def test_settings_view_has_one_field_per_schema_entry():
    from app.core.config.settings_store import SETTINGS_SCHEMA

    store = make_store()
    config = AppSettings()
    store.load_into(config)

    view = build_settings_view(config, store)
    _, fields = _collect(view)

    assert len(fields) == len(SETTINGS_SCHEMA)


def test_saving_valid_changes_updates_the_live_config():
    store = make_store()
    config = AppSettings()
    store.load_into(config)

    view = build_settings_view(config, store)
    button, fields = _collect(view)

    entry_field = next(f for label, f in fields.items() if "Giriş Eşiği" in label)
    entry_field.value = "7.0"

    _click_save(button)

    assert config.strategy.entry_percent == 7.0

    # And it must have actually persisted, not just mutated in memory.
    reloaded = AppSettings()
    store.load_into(reloaded)
    assert reloaded.strategy.entry_percent == 7.0


def test_saving_invalid_value_does_not_mutate_config():
    store = make_store()
    config = AppSettings()
    store.load_into(config)
    original_entry_percent = config.strategy.entry_percent

    view = build_settings_view(config, store)
    button, fields = _collect(view)

    entry_field = next(f for label, f in fields.items() if "Giriş Eşiği" in label)
    entry_field.value = "not-a-number"

    _click_save(button)

    assert config.strategy.entry_percent == original_entry_percent
