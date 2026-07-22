import ccxt

from app.ui.app import (
    _describe_startup_error,
    _show_startup_error_dialog,
    _start_engine_in_background,
)


class DummyPage:
    """Records show_dialog()/pop_dialog()/update() calls without needing
    a real running Flet session (B25 regression tests)."""

    def __init__(self):
        self.shown_dialogs = []
        self.update_calls = 0

    def show_dialog(self, dialog):
        self.shown_dialogs.append(dialog)

    def pop_dialog(self):
        return None

    def update(self):
        self.update_calls += 1


class DummyEngine:
    def __init__(self, error=None):
        self._error = error
        self.started = False

    def start(self):
        self.started = True
        if self._error is not None:
            raise self._error


# ---------------------------------------------------------------------
# _describe_startup_error
# ---------------------------------------------------------------------

def test_describe_startup_error_for_authentication_error():
    title, message = _describe_startup_error(
        ccxt.AuthenticationError("invalid key")
    )

    assert "Kimlik" in title
    assert "API" in message


def test_describe_startup_error_for_network_error():
    title, message = _describe_startup_error(ccxt.NetworkError("timeout"))

    assert "Bağlantı" in title


def test_describe_startup_error_for_generic_exception():
    title, message = _describe_startup_error(ValueError("boom"))

    assert "Başlatma" in title
    assert "boom" in message


# ---------------------------------------------------------------------
# _show_startup_error_dialog
# ---------------------------------------------------------------------

def test_show_startup_error_dialog_shows_and_updates_page():
    page = DummyPage()

    _show_startup_error_dialog(page, ccxt.NetworkError("no connection"))

    assert len(page.shown_dialogs) == 1
    assert page.update_calls == 1


# ---------------------------------------------------------------------
# _start_engine_in_background (B25: engine.start() off the UI thread)
# ---------------------------------------------------------------------

def test_start_engine_in_background_runs_engine_start():
    page = DummyPage()
    engine = DummyEngine()

    _start_engine_in_background(page, engine)

    assert engine.started is True
    assert page.shown_dialogs == []  # no error -> no dialog


def test_start_engine_in_background_shows_dialog_on_authentication_error():
    page = DummyPage()
    engine = DummyEngine(error=ccxt.AuthenticationError("bad key"))

    # Must not raise -- the failure is caught and surfaced via a dialog
    # instead of crashing the background thread silently.
    _start_engine_in_background(page, engine)

    assert engine.started is True
    assert len(page.shown_dialogs) == 1


def test_start_engine_in_background_shows_dialog_on_unexpected_error():
    page = DummyPage()
    engine = DummyEngine(error=RuntimeError("unexpected"))

    _start_engine_in_background(page, engine)

    assert len(page.shown_dialogs) == 1
