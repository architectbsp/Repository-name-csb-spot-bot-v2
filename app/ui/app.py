import logging
from pathlib import Path
import threading

import ccxt
import flet as ft

from app.core.bot_engine import BotEngine
from app.core.exchange.factory import supported_exchange_names
from app.ui.api_config import (
    ExchangeCredentialsSession,
    requires_passphrase,
)
from app.ui.components.account_panel import build_account_panel
from app.ui.components.bot_log import build_bot_log
from app.ui.components.coin_table import build_coin_table
from app.ui.components.content import build_dashboard_view
from app.ui.components.cooldown import build_cooldown
from app.ui.components.dashboard_cards import build_dashboard_cards
from app.ui.components.open_positions import build_open_positions
from app.ui.components.recent_signals import build_recent_signals
from app.ui.components.settings_panel import build_settings_view
from app.ui.components.sidebar import (
    DASHBOARD,
    LOGS,
    MARKET,
    PORTFOLIO,
    POSITIONS,
    SCANNER,
    SETTINGS,
    SIGNALS,
    build_sidebar,
)
from app.ui.components.top_bar import build_top_bar
from app.ui.components.trade_history import build_trade_history
from app.ui.theme import setup_page


logger = logging.getLogger(__name__)

# How often the live dashboard rebuilds itself from DashboardService.
# Short enough to feel real-time for positions/watch state; long enough
# that we never REST-spam (ticker prices come from the in-memory cache
# fed by ticker.updated, not from a balance/ticker REST call every tick
# -- only quote_balance hits the exchange, and that is best-effort).
_DASHBOARD_POLL_SECONDS = 2.0
_ENV_PATH = Path(".env")


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


def _show_info_dialog(page: ft.Page, title: str, lines: list[str]) -> None:
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Column(
            tight=True,
            spacing=6,
            controls=[ft.Text(line) for line in lines],
        ),
        actions=[ft.TextButton("Kapat", on_click=lambda _: page.pop_dialog())],
    )
    page.show_dialog(dialog)
    page.update()


def _show_api_config_dialog(page: ft.Page, engine: BotEngine) -> None:
    """
    Per-exchange isolated API settings dialog.

    Each venue has its own draft in ``ExchangeCredentialsSession``. Switching
    exchanges captures the current fields into that venue's draft only, then
    loads the newly selected venue's independent draft into the controls.
    """
    supported = [name.lower() for name in supported_exchange_names()]
    session = ExchangeCredentialsSession(_ENV_PATH, supported)

    exchange_cfg = engine.config.exchange
    exchange_value = (exchange_cfg.exchange or "binance").strip().lower()
    if exchange_value not in session.exchanges:
        exchange_value = supported[0] if supported else "binance"

    # Track the exchange whose fields are currently bound to the controls.
    current = {"exchange": exchange_value}

    status = ft.Text("", size=11, color="#94A3B8")
    exchange_field = ft.Dropdown(
        label="Exchange",
        value=exchange_value.upper(),
        options=[ft.dropdown.Option(name.upper()) for name in supported],
        width=520,
        dense=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
    )
    market_mode_field = ft.Dropdown(
        label="Market Mode",
        value="TESTNET",
        options=[
            ft.dropdown.Option("REAL"),
            ft.dropdown.Option("TESTNET"),
        ],
        width=520,
        dense=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
    )
    api_key_field = ft.TextField(
        label="API Key",
        value="",
        width=520,
        dense=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
    )
    api_secret_field = ft.TextField(
        label="API Secret",
        value="",
        width=520,
        dense=True,
        password=True,
        can_reveal_password=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
    )
    passphrase_field = ft.TextField(
        label="Passphrase",
        value="",
        width=520,
        dense=True,
        password=True,
        can_reveal_password=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
        visible=requires_passphrase(exchange_value),
    )

    def _capture_current_fields() -> None:
        selected_mode = (market_mode_field.value or "").strip().upper()
        session.capture(
            current["exchange"],
            api_key=api_key_field.value or "",
            api_secret=api_secret_field.value or "",
            passphrase=passphrase_field.value or "",
            testnet=selected_mode != "REAL",
        )

    def _apply_draft_to_fields(exchange_name: str) -> None:
        draft = session.snapshot(exchange_name)
        market_mode_field.value = "TESTNET" if draft.testnet else "REAL"
        api_key_field.value = draft.api_key
        api_secret_field.value = draft.api_secret
        passphrase_field.value = draft.passphrase
        passphrase_field.visible = requires_passphrase(exchange_name)
        market_mode_field.update()
        api_key_field.update()
        api_secret_field.update()
        passphrase_field.update()
        if draft.validation_error:
            status.value = draft.validation_error
            status.color = "#EF4444"
        else:
            status.value = f"{exchange_name.upper()} ayarları yüklendi."
            status.color = "#22C55E"
        status.update()

    def _on_exchange_change(event) -> None:
        next_exchange = (event.control.value or "").strip().lower()
        if not next_exchange or next_exchange not in session.exchanges:
            return
        if next_exchange == current["exchange"]:
            return
        # Stash the leaving exchange's UI values into ITS draft only.
        _capture_current_fields()
        current["exchange"] = next_exchange
        _apply_draft_to_fields(next_exchange)

    exchange_field.on_change = _on_exchange_change

    def _load(_=None) -> None:
        _capture_current_fields()
        selected = (exchange_field.value or "").strip().lower()
        # Reload all venues from disk, then refresh only the selected UI.
        session.reload_from_disk()
        current["exchange"] = selected if selected in session.exchanges else current["exchange"]
        exchange_field.value = current["exchange"].upper()
        exchange_field.update()
        _apply_draft_to_fields(current["exchange"])
        status.value = "Yüklendi (.env — borsa başına bağımsız)"
        status.color = "#22C55E"
        status.update()

    def _save(_=None) -> None:
        selected_exchange = (exchange_field.value or "").strip().lower()
        if selected_exchange not in session.exchanges:
            status.value = "Geçersiz borsa seçimi."
            status.color = "#EF4444"
            status.update()
            return
        selected_mode = (market_mode_field.value or "").strip().upper()
        if selected_mode not in {"REAL", "TESTNET"}:
            status.value = "Geçersiz market modu."
            status.color = "#EF4444"
            status.update()
            return

        # Ensure current fields belong to the selected exchange's draft only.
        current["exchange"] = selected_exchange
        _capture_current_fields()
        error = session.validate(selected_exchange)
        if error:
            status.value = error
            status.color = "#EF4444"
            status.update()
            return

        try:
            session.persist(selected_exchange)
        except OSError as exc:
            logger.exception("Failed to persist API config")
            status.value = f"Kaydetme hatası: {type(exc).__name__}"
            status.color = "#EF4444"
            status.update()
            return

        draft = session.snapshot(selected_exchange)
        # Active runtime primary exchange only — not a shared multi-venue model.
        engine.config.exchange.exchange = selected_exchange
        engine.config.exchange.testnet = draft.testnet
        engine.config.exchange.api_key = draft.api_key
        engine.config.exchange.api_secret = draft.api_secret
        engine.config.exchange.passphrase = (
            draft.passphrase if requires_passphrase(selected_exchange) else ""
        )
        status.value = (
            f"{selected_exchange.upper()} kaydedildi (.env) — "
            "diğer borsalar değişmedi. Sonraki başlatmada uygulanır."
        )
        status.color = "#22C55E"
        status.update()

    # Initial bind from the selected exchange's independent draft.
    _apply_draft_to_fields(current["exchange"])

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"API Ayarları ({current['exchange'].upper()})"),
        content=ft.Column(
            tight=True,
            spacing=8,
            controls=[
                exchange_field,
                market_mode_field,
                api_key_field,
                api_secret_field,
                passphrase_field,
                status,
            ],
        ),
        actions=[
            ft.TextButton("Load", on_click=_load),
            ft.TextButton("Save", on_click=_save),
            ft.TextButton("Close", on_click=lambda _: page.pop_dialog()),
        ],
    )
    page.show_dialog(dialog)
    page.update()


def _build_notifications(alerts: list[dict]) -> ft.Container:
    rows: list[ft.Control]
    if not alerts:
        rows = [ft.Text("Henüz bildirim yok.", color="#64748B", size=12)]
    else:
        rows = [
            ft.Container(
                padding=8,
                border_radius=8,
                bgcolor="#131C2B",
                content=ft.Text(
                    f"{a.get('at', '-')}: {a.get('symbol', '?')} "
                    f"{a.get('side', '?')} {a.get('outcome', '?')}",
                    color="#F8FAFC",
                    size=12,
                ),
            )
            for a in alerts[-12:]
        ]
    return ft.Container(
        bgcolor="#0B1220",
        border_radius=12,
        padding=15,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Text("NOTIFICATIONS", color="white", size=15, weight=ft.FontWeight.BOLD),
                *rows,
            ],
        ),
    )


def _build_view(
    view_name: str,
    engine: BotEngine,
    page: ft.Page,
    on_navigate,
    coin_search_query: str = "",
    on_coin_search=None,
    on_coin_refresh=None,
):
    def _on_top_action(action: str) -> None:
        if action == "LOG":
            on_navigate(LOGS)
            return
        if action == "SETTINGS":
            on_navigate(SETTINGS)
            return
        if action == "API":
            _show_api_config_dialog(page, engine)
            return
        if action == "TELEGRAM":
            tg = engine.config.telegram
            _show_info_dialog(
                page,
                "Telegram",
                [
                    f"Enabled: {'yes' if tg.enabled else 'no'}",
                    f"Bot token: {'configured' if bool(tg.bot_token) else 'missing'}",
                    f"Chat ID: {tg.chat_id or 'missing'}",
                    f"Admin Chat ID: {tg.admin_chat_id or 'missing'}",
                ],
            )

    if view_name == SETTINGS:
        return build_settings_view(
            engine.config,
            engine.settings_store,
            engine=engine,
        )

    snapshot = engine.dashboard_service.build_snapshot()
    if view_name == DASHBOARD:
        return build_dashboard_view(
            engine,
            page,
            snapshot,
            on_top_action=_on_top_action,
            coin_search_query=coin_search_query,
            on_coin_search=on_coin_search,
            on_coin_refresh=on_coin_refresh,
        )
    if view_name == MARKET:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                build_coin_table(
                    engine,
                    page,
                    snapshot,
                    search_query=coin_search_query,
                    on_search=on_coin_search,
                    on_refresh=on_coin_refresh,
                ),
            ],
        )
    if view_name == SCANNER:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                ft.Row(
                    expand=True,
                    spacing=15,
                    controls=[
                        ft.Container(expand=2, content=build_recent_signals(snapshot)),
                        ft.Container(expand=1, content=build_cooldown(snapshot)),
                    ],
                ),
            ],
        )
    if view_name == POSITIONS:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                build_open_positions(engine, page, snapshot),
            ],
        )
    if view_name == PORTFOLIO:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                build_dashboard_cards(snapshot),
                build_account_panel(snapshot),
            ],
        )
    if view_name == SIGNALS:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                ft.Row(
                    spacing=15,
                    controls=[
                        ft.Container(expand=1, content=build_recent_signals(snapshot)),
                        ft.Container(expand=1, content=build_trade_history(snapshot)),
                    ],
                ),
                _build_notifications(engine.dashboard_service.recent_execution_alerts()),
            ],
        )
    if view_name == LOGS:
        return ft.Column(
            expand=True,
            spacing=15,
            controls=[
                build_top_bar(snapshot, on_action=_on_top_action),
                build_bot_log(snapshot),
                _build_notifications(engine.dashboard_service.recent_execution_alerts()),
            ],
        )
    return build_dashboard_view(
        engine,
        page,
        snapshot,
        on_top_action=_on_top_action,
        coin_search_query=coin_search_query,
        on_coin_search=on_coin_search,
        on_coin_refresh=on_coin_refresh,
    )


def main(page: ft.Page):
    setup_page(page)

    engine = BotEngine()
    stop_event = threading.Event()
    current_view = {"name": DASHBOARD}
    coin_search = {"query": ""}

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
        content=None,
    )

    sidebar_area = ft.Container()

    def _handle_coin_refresh(_=None) -> None:
        try:
            engine.scanner.tick()
        except Exception as exc:
            logger.exception("Manual scanner refresh failed")
            _show_info_dialog(
                page,
                "Refresh Hatası",
                [f"Scanner refresh başarısız: {exc}"],
            )
            return
        navigate(current_view["name"])

    def _handle_coin_search(event) -> None:
        coin_search["query"] = (getattr(event.control, "value", "") or "").strip()
        navigate(current_view["name"])

    def navigate(view_name: str) -> None:
        current_view["name"] = view_name
        sidebar_area.content = build_sidebar(view_name, navigate)
        content_area.content = _build_view(
            view_name,
            engine,
            page,
            navigate,
            coin_search_query=coin_search["query"],
            on_coin_search=_handle_coin_search,
            on_coin_refresh=_handle_coin_refresh,
        )
        sidebar_area.update()
        content_area.update()

    sidebar_area.content = build_sidebar(DASHBOARD, navigate)
    content_area.content = _build_view(
        DASHBOARD,
        engine,
        page,
        navigate,
        coin_search_query=coin_search["query"],
        on_coin_search=_handle_coin_search,
        on_coin_refresh=_handle_coin_refresh,
    )

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
            if current_view["name"] == SETTINGS:
                continue
            try:
                content_area.content = _build_view(
                    current_view["name"],
                    engine,
                    page,
                    navigate,
                )
                content_area.update()
            except Exception:
                logger.exception("Live dashboard refresh failed")

    page.run_thread(_start_engine_in_background, page, engine)
    page.run_thread(_refresh_dashboard_loop)
