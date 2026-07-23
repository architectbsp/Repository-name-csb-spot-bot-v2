"""
Sprint 1/2: no strategy/risk parameter may stay hardcoded, and any change
persisted through SettingsStore must be usable live (no restart) because
it mutates the shared AppSettings instance in place.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config.settings import AppSettings
from app.core.config.settings_store import SETTINGS_SCHEMA, SettingsStore
from app.core.persistence.database import Base
from app.core.persistence.repository import SettingsRepository


def make_store() -> SettingsStore:
    """An isolated in-memory SQLite settings store, independent from the
    real on-disk database used by the running app."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, future=True)()
    return SettingsStore(SettingsRepository(session))


def test_load_into_persists_compiled_defaults_on_first_run():
    store = make_store()
    app_settings = AppSettings()

    store.load_into(app_settings)

    # Nothing was persisted yet -- the compiled-in defaults must now be
    # saved so a Settings screen has a baseline row to show/update.
    values = store.current_values(app_settings)
    assert values["watch_percent"] == AppSettings().strategy.watch_percent


def test_every_schema_field_round_trips_through_persistence():
    store = make_store()
    app_settings = AppSettings()
    store.load_into(app_settings)

    changes = {}
    for field in SETTINGS_SCHEMA:
        if field.name in {"trading_start_time", "trading_end_time"}:
            changes[field.name] = "09:30" if field.name.endswith("start_time") else "18:00"
        elif field.value_type is str:
            changes[field.name] = "TEST_VALUE"
        else:
            changes[field.name] = field.minimum
    errors = store.update(app_settings, changes)

    assert errors == []

    for field in SETTINGS_SCHEMA:
        section = getattr(app_settings, field.section)
        if field.name == "trading_start_time":
            expected = "09:30"
        elif field.name == "trading_end_time":
            expected = "18:00"
        elif field.value_type is str:
            expected = "TEST_VALUE"
        else:
            expected = field.value_type(field.minimum)
        assert getattr(section, field.name) == expected

    # A brand new AppSettings loaded from the same store must see the
    # persisted values, proving the round trip through SQLite.
    reloaded = AppSettings()
    store.load_into(reloaded)

    for field in SETTINGS_SCHEMA:
        section = getattr(reloaded, field.section)
        if field.name == "trading_start_time":
            expected = "09:30"
        elif field.name == "trading_end_time":
            expected = "18:00"
        elif field.value_type is str:
            expected = "TEST_VALUE"
        else:
            expected = field.value_type(field.minimum)
        assert getattr(section, field.name) == expected


def test_update_mutates_the_same_instance_in_place_for_live_reload():
    """
    Sprint 2: Strategy/WatchList/RiskManager/MarketScanner all hold a
    reference to the *same* AppSettings object handed to them at wiring
    time. update() must mutate that object's nested dataclasses in place
    (not replace app_settings.risk/strategy with new objects), otherwise
    already-wired modules would keep reading stale values.
    """
    store = make_store()
    app_settings = AppSettings()
    store.load_into(app_settings)

    risk_section_identity = id(app_settings.risk)
    strategy_section_identity = id(app_settings.strategy)

    store.update(app_settings, {"stop_loss_percent": 12.0, "entry_percent": 7.0})

    assert id(app_settings.risk) == risk_section_identity
    assert id(app_settings.strategy) == strategy_section_identity
    assert app_settings.risk.stop_loss_percent == 12.0
    assert app_settings.strategy.entry_percent == 7.0


def test_update_rejects_out_of_range_values_and_applies_nothing():
    store = make_store()
    app_settings = AppSettings()
    store.load_into(app_settings)

    original_stop_loss = app_settings.risk.stop_loss_percent

    errors = store.update(
        app_settings,
        {"stop_loss_percent": 999.0, "entry_percent": 7.0},
    )

    assert len(errors) == 1
    # All-or-nothing: even the valid field in the same batch must not be
    # applied when another field in the batch fails validation.
    assert app_settings.risk.stop_loss_percent == original_stop_loss
    assert app_settings.strategy.entry_percent != 7.0


def test_update_rejects_non_numeric_values():
    store = make_store()
    app_settings = AppSettings()
    store.load_into(app_settings)

    errors = store.update(app_settings, {"max_open_positions": "not-a-number"})

    assert len(errors) == 1


def test_update_ignores_unknown_field_names():
    store = make_store()
    app_settings = AppSettings()
    store.load_into(app_settings)

    errors = store.update(app_settings, {"totally_unknown_field": 1})

    assert errors == []


def test_schema_covers_every_field_the_user_requested():
    names = {field.name for field in SETTINGS_SCHEMA}

    assert names == {
        "watch_percent",
        "entry_percent",
        "stop_loss_percent",
        "trailing_activation_percent",
        "trailing_percent",
        "cooldown_hours",
        "max_open_positions",
        "scan_interval_seconds",
        "min_volume_usd",
        "trading_hours_enabled",
        "disable_weekend_trading",
        "trading_start_time",
        "trading_end_time",
        "blacklist_symbols",
        "filtered_patterns",
        "max_balance_utilization_percent",
        "max_volume_share_percent",
        "position_sizing_mode",
        "risk_per_trade_percent",
        "atr_period",
        "atr_multiplier",
        "volatility_target_percent",
        "volatility_lookback",
        "kelly_fraction",
        "kelly_min_trades",
        "dynamic_lookback_trades",
        "max_position_hours",
        "max_daily_loss_percent",
        "partial_tp_activation_percent",
        "partial_tp_sell_percent",
    }
