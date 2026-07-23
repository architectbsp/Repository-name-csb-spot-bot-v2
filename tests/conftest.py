"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.core.config.config_manager import ConfigManager


@pytest.fixture(autouse=True)
def _reset_config_manager():
    """Isolate ConfigManager singleton across tests."""
    ConfigManager.reset_instance()
    yield
    ConfigManager.reset_instance()
