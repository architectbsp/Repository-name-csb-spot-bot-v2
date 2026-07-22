"""
Sprint 1/2 Settings screen: every strategy/risk knob in
app.core.config.settings_store.SETTINGS_SCHEMA is editable here, saved to
SQLite via ConfigManager, and applied live (no bot restart). Kaydet
publishes ConfigUpdatedEvent (`config.updated`) so Strategy / Scanner /
RiskManager observers refresh without a restart.
"""

import flet as ft

from app.core.config.config_manager import ConfigManager
from app.core.config.settings_store import SETTINGS_SCHEMA, SettingsStore


_SECTION_TITLES = {
    "strategy": "Strateji Parametreleri",
    "risk": "Risk Yönetimi",
}


def build_settings_view(config, settings_store: SettingsStore) -> ft.Column:
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
        # Prefer the wired singleton; fall back to direct store update in
        # unit tests that build the panel without BotEngine.
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
            # Reflect whatever was actually persisted/clamped back into
            # the form so the UI never shows a value that wasn't applied.
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
        ],
    )
