"""
ConfigManager -- singleton facade over SettingsStore + AppSettings.

Prompt mapping (Darphane / Sprint 1-2):
  watch_pct              -> strategy.watch_percent
  entry_pct              -> strategy.entry_percent
  stop_loss              -> risk.stop_loss_percent
  break_even             -> risk.trailing_activation_percent  (same knob)
  trailing_activation    -> risk.trailing_activation_percent
  trailing_pct           -> risk.trailing_percent
  cooldown               -> risk.cooldown_hours
  max_position           -> risk.max_open_positions
  scan_interval          -> strategy.scan_interval_seconds
  min_volume             -> strategy.min_volume_usd
  capital_pct            -> risk.max_balance_utilization_percent
                           (dynamic liquidity sizing; no fixed capital %)
  take_profit_activation -> risk.partial_tp_activation_percent
                           (0 = off; profit otherwise via trailing)
  max_daily_loss         -> risk.max_daily_loss_percent

Persistence: SQLite `bot_settings` via SettingsStore (primary). Optional
`config.json` mirror when CONFIG_JSON_PATH is set / default path exists
for export. Runtime reload: save() mutates the shared AppSettings in
place AND publishes `config.updated` (ConfigUpdatedEvent) on the
EventBus so Strategy / MarketScanner / RiskManager can react.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config.settings import AppSettings
from app.core.config.settings_store import SETTINGS_SCHEMA, SettingsStore


logger = logging.getLogger(__name__)

CONFIG_UPDATED_EVENT = "config.updated"

# Prompt names -> SETTINGS_SCHEMA field names.
PARAM_ALIASES: dict[str, str] = {
    "watch_pct": "watch_percent",
    "entry_pct": "entry_percent",
    "stop_loss": "stop_loss_percent",
    "break_even": "trailing_activation_percent",
    "trailing_activation": "trailing_activation_percent",
    "trailing_pct": "trailing_percent",
    "cooldown": "cooldown_hours",
    "max_position": "max_open_positions",
    "scan_interval": "scan_interval_seconds",
    "min_volume": "min_volume_usd",
    "capital_pct": "max_balance_utilization_percent",
    "take_profit_activation": "partial_tp_activation_percent",
    "max_daily_loss": "max_daily_loss_percent",
}


@dataclass(frozen=True, slots=True)
class ConfigUpdatedEvent:
    """Payload published on EventBus as `config.updated` after a successful save."""

    changed: dict[str, Any]
    values: dict[str, Any]
    source: str = "settings_ui"
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ConfigManager:
    """
    Process-wide singleton. Wire once from BotEngine with the shared
    AppSettings + SettingsStore (+ EventBus), then use ConfigManager.instance().
    """

    _instance: "ConfigManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._settings: AppSettings | None = None
        self._store: SettingsStore | None = None
        self._event_bus = None
        self._json_path: Path | None = None
        self._json_export_enabled: bool = False

    @classmethod
    def instance(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Test helper -- drops the singleton."""
        with cls._lock:
            cls._instance = None

    def configure(
        self,
        settings: AppSettings,
        store: SettingsStore,
        event_bus=None,
        *,
        json_path: str | Path | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._event_bus = event_bus
        env_path = (os.getenv("CONFIG_JSON_PATH") or "").strip()
        if json_path is not None:
            self._json_path = Path(json_path)
            self._json_export_enabled = True
        elif env_path:
            self._json_path = Path(env_path)
            self._json_export_enabled = True
        else:
            # Default mirror path; only write if the file already exists
            # (operator opted in by creating it) or CONFIG_JSON_PATH is set.
            self._json_path = Path("config.json")
            self._json_export_enabled = self._json_path.is_file()

    @property
    def is_configured(self) -> bool:
        return self._settings is not None and self._store is not None

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            raise RuntimeError("ConfigManager is not configured.")
        return self._settings

    @property
    def store(self) -> SettingsStore:
        if self._store is None:
            raise RuntimeError("ConfigManager is not configured.")
        return self._store

    def load(self) -> None:
        """Loads SQLite row into the live AppSettings (in place)."""
        self.store.load_into(self.settings)
        self._maybe_import_json_overlay()

    def values(self) -> dict[str, Any]:
        return self.store.current_values(self.settings)

    def save(
        self,
        changes: dict[str, object] | None = None,
        *,
        source: str = "settings_ui",
    ) -> list[str]:
        """
        Validates + persists `changes` (prompt aliases accepted), mutates
        live AppSettings, mirrors config.json, publishes ConfigUpdatedEvent.
        Returns validation errors (empty list = success).
        """
        normalized = self._normalize_changes(changes or {})
        before = self.values()
        errors = self.store.update(self.settings, normalized)
        if errors:
            return errors

        after = self.values()
        changed = {
            key: after[key]
            for key in after
            if before.get(key) != after[key]
        }
        # If caller passed an explicit subset, report those keys even when
        # value equal (operator forced re-save).
        if normalized and not changed:
            changed = {k: after[k] for k in normalized if k in after}

        self._export_json()
        self._publish_updated(changed, after, source=source)
        return []

    def _normalize_changes(self, changes: dict[str, object]) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in changes.items():
            name = PARAM_ALIASES.get(key, key)
            if name == "position_sizing_mode":
                from app.core.risk_manager import resolve_position_sizing_mode

                try:
                    value = resolve_position_sizing_mode(value)
                except ValueError:
                    # Leave raw value for SettingsStore validation error path.
                    pass
            out[name] = value
        return out

    def _publish_updated(
        self,
        changed: dict[str, Any],
        values: dict[str, Any],
        *,
        source: str,
    ) -> None:
        if self._event_bus is None:
            return
        event = ConfigUpdatedEvent(
            changed=changed,
            values=values,
            source=source,
        )
        self._event_bus.publish(CONFIG_UPDATED_EVENT, event)
        logger.info(
            "[CONFIG] config.updated source=%s changed=%s",
            source,
            sorted(changed.keys()),
        )

    def _export_json(self) -> None:
        if self._json_path is None or not self._json_export_enabled:
            return
        try:
            payload = {
                "updated_at": datetime.now(UTC).isoformat(),
                "values": self.values(),
            }
            self._json_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            logger.exception(
                "[CONFIG] Failed to mirror settings to %s", self._json_path
            )

    def _maybe_import_json_overlay(self) -> None:
        """
        Optional: if config.json exists and CONFIG_JSON_IMPORT=true,
        overlay its values onto the live settings (then persist to DB).
        Off by default so a stale file cannot clobber SQLite on boot.
        """
        if self._json_path is None or not self._json_path.is_file():
            return
        flag = (os.getenv("CONFIG_JSON_IMPORT") or "").strip().lower()
        if flag not in {"1", "true", "yes", "on"}:
            return
        try:
            raw = json.loads(self._json_path.read_text(encoding="utf-8"))
            values = raw.get("values") if isinstance(raw, dict) else None
            if not isinstance(values, dict):
                return
            errors = self.store.update(self.settings, values)
            if errors:
                logger.warning("[CONFIG] config.json import errors: %s", errors)
        except Exception:
            logger.exception("[CONFIG] Failed to import %s", self._json_path)


def schema_covers_prompt_params() -> dict[str, str]:
    """Returns prompt alias -> schema field for every alias that exists in SETTINGS_SCHEMA."""
    schema_names = {f.name for f in SETTINGS_SCHEMA}
    return {
        alias: name
        for alias, name in PARAM_ALIASES.items()
        if name in schema_names
    }
