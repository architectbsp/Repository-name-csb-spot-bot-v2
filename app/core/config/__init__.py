"""
CSB Spot Bot configuration package.

``ConfigManager`` is the process-wide singleton SettingsService facade
(load / save / runtime reload via ``config.updated``).
"""

from app.core.config.config_manager import (
    CONFIG_UPDATED_EVENT,
    PARAM_ALIASES,
    ConfigManager,
    ConfigUpdatedEvent,
    schema_covers_prompt_params,
)
from app.core.config.settings import AppSettings
from app.core.config.settings_store import SETTINGS_SCHEMA, SettingsStore, apply_schema_values

# Alias matching the SettingsService naming in the dynamic-config brief.
SettingsService = ConfigManager

__all__ = [
    "AppSettings",
    "CONFIG_UPDATED_EVENT",
    "ConfigManager",
    "ConfigUpdatedEvent",
    "PARAM_ALIASES",
    "SETTINGS_SCHEMA",
    "SettingsService",
    "SettingsStore",
    "apply_schema_values",
    "schema_covers_prompt_params",
]
