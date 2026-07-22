from datetime import UTC, datetime

from app.core.services.trading_hours import block_reason, is_entry_allowed


def test_disabled_hours_always_allow():
    assert is_entry_allowed(
        enabled=False,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=datetime(2026, 7, 25, 3, 0, tzinfo=UTC),  # Saturday 03:00
    )


def test_quiet_hours_block_new_entries():
    now = datetime(2026, 7, 23, 3, 30, tzinfo=UTC)  # Thursday 03:30
    assert not is_entry_allowed(
        enabled=True,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    )
    assert block_reason(
        enabled=True,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    ) == "quiet_hours"


def test_outside_quiet_hours_allows_weekday():
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)  # Thursday 10:00
    assert is_entry_allowed(
        enabled=True,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    )


def test_weekend_closed():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)  # Saturday noon
    assert not is_entry_allowed(
        enabled=True,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    )
    assert block_reason(
        enabled=True,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    ) == "weekend_closed"


def test_quiet_window_wraps_midnight():
    # Quiet 22:00–06:00
    assert not is_entry_allowed(
        enabled=True,
        weekend_closed=False,
        quiet_start_hour_utc=22,
        quiet_end_hour_utc=6,
        now=datetime(2026, 7, 23, 23, 0, tzinfo=UTC),
    )
    assert is_entry_allowed(
        enabled=True,
        weekend_closed=False,
        quiet_start_hour_utc=22,
        quiet_end_hour_utc=6,
        now=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )
