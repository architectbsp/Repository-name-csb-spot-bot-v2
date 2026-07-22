"""
Settings screen: every strategy/risk knob in SETTINGS_SCHEMA plus the
operator-managed symbol blacklist.
"""

from __future__ import annotations

import flet as ft

from app.core.config.config_manager import ConfigManager
from app.core.config.settings_store import SETTINGS_SCHEMA, SettingsStore


_SECTION_TITLES = {
    "strategy": "Strateji Parametreleri",
    "risk": "Risk Yönetimi",
}


def _blacklist_card(symbol_filter) -> ft.Container:
    status = ft.Text("", size=11, color="#94A3B8")
    input_field = ft.TextField(
        label="Sembol (örn. SHIB/USDT veya LUNA)",
        width=280,
        dense=True,
        border_color="#273449",
        focused_border_color="#3B82F6",
        color="#F8FAFC",
        label_style=ft.TextStyle(color="#94A3B8", size=12),
    )
    list_view = ft.Column(spacing=4, tight=True)

    def _refresh_list() -> None:
        symbols = (
            symbol_filter.list_blacklist()
            if symbol_filter is not None
            else []
        )
        if not symbols:
            list_view.controls = [
                ft.Text("Kara liste boş", size=12, color="#64748B"),
            ]
            return

        def _make_remove(sym: str):
            def _handler(_):
                if symbol_filter is None:
                    return
                symbol_filter.remove(sym)
                status.value = f"{sym} kaldırıldı"
                status.color = "#22C55E"
                _refresh_list()
                status.update()
                list_view.update()

            return _handler

        list_view.controls = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text(sym, color="#F8FAFC", size=12),
                    ft.TextButton(
                        "Kaldır",
                        on_click=_make_remove(sym),
                        style=ft.ButtonStyle(color="#EF4444"),
                    ),
                ],
            )
            for sym in symbols
        ]

    def _on_add(_):
        if symbol_filter is None:
            status.value = "Kara liste servisi yok"
            status.color = "#EF4444"
            status.update()
            return
        raw = (input_field.value or "").strip()
        if not raw:
            status.value = "Sembol girin"
            status.color = "#EF4444"
            status.update()
            return
        try:
            key = symbol_filter.add(raw)
        except Exception as exc:
            status.value = f"Hata: {exc}"
            status.color = "#EF4444"
            status.update()
            return
        input_field.value = ""
        status.value = f"{key} eklendi (UP/DOWN/3L/3S zaten otomatik engelli)"
        status.color = "#22C55E"
        _refresh_list()
        input_field.update()
        status.update()
        list_view.update()

    _refresh_list()

    return ft.Container(
        bgcolor="#0B1220",
        border_radius=14,
        padding=20,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text(
                    "Coin Kara Listesi",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color="#F8FAFC",
                ),
                ft.Text(
                    "UP / DOWN / 3L / 3S / BULL / BEAR ekleri tarayıcıda "
                    "otomatik engellenir. Aşağıya elle eklediğiniz "
                    "semboller de taranmaz.",
                    size=11,
                    color="#94A3B8",
                ),
                ft.Row(
                    spacing=10,
                    controls=[
                        input_field,
                        # TextButton (not Button) so headless settings tests
                        # still find "Kaydet" as the only primary Button.
                        ft.TextButton(
                            "Ekle",
                            on_click=_on_add,
                            disabled=symbol_filter is None,
                            style=ft.ButtonStyle(color="#3B82F6"),
                        ),
                    ],
                ),
                status,
                list_view,
            ],
        ),
    )


def build_settings_view(
    config,
    settings_store: SettingsStore,
    engine=None,
) -> ft.Column:
    status_text = ft.Text("", size=12)

    fields: dict[str, ft.TextField] = {}

    for field in SETTINGS_SCHEMA:
        section = getattr(config, field.section)
        current_value = getattr(section, field.name)

        fields[field.name] = ft.TextField(
            label=f"{field.label} ({field.unit})",
            value=str(current_value),
            width=320,
            dense=True,
            border_color="#273449",
            focused_border_color="#3B82F6",
            color="#F8FAFC",
            label_style=ft.TextStyle(color="#94A3B8", size=12),
            helper=f"{field.minimum} - {field.maximum} arası",
            helper_style=ft.TextStyle(color="#64748B", size=10),
        )

    def _on_save(_):
        changes = {name: field.value for name, field in fields.items()}
        manager = ConfigManager.instance()
        if manager.is_configured:
            errors = manager.save(changes, source="settings_ui")
        else:
            errors = settings_store.update(config, changes)

        if errors:
            status_text.value = "Hata: " + " | ".join(errors)
            status_text.color = "#EF4444"
        else:
            status_text.value = (
                "Ayarlar kaydedildi ve anında etkinleştirildi "
                "(yeniden başlatma gerekmez)."
            )
            status_text.color = "#22C55E"
            for f in SETTINGS_SCHEMA:
                section = getattr(config, f.section)
                fields[f.name].value = str(getattr(section, f.name))

        status_text.update()
        for f in fields.values():
            f.update()

    def _section_card(section_key: str) -> ft.Container:
        section_fields = [f for f in SETTINGS_SCHEMA if f.section == section_key]

        return ft.Container(
            bgcolor="#0B1220",
            border_radius=14,
            padding=20,
            content=ft.Column(
                spacing=14,
                controls=[
                    ft.Text(
                        _SECTION_TITLES[section_key],
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color="#F8FAFC",
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=16,
                        run_spacing=14,
                        controls=[fields[f.name] for f in section_fields],
                    ),
                ],
            ),
        )

    symbol_filter = getattr(engine, "symbol_filter", None) if engine else None

    return ft.Column(
        expand=True,
        spacing=15,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text(
                        "Ayarlar",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color="#F8FAFC",
                    ),
                    ft.Button(
                        "Kaydet",
                        icon=ft.Icons.SAVE,
                        bgcolor="#3B82F6",
                        color="#FFFFFF",
                        on_click=_on_save,
                    ),
                ],
            ),
            status_text,
            _section_card("strategy"),
            _section_card("risk"),
            _blacklist_card(symbol_filter),
        ],
    )
