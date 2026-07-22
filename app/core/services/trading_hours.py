"""
Trading Hours Constraint -- blocks *new entries* outside the configured
UTC windows. Open positions continue to be managed (stops / trailing /
manual / emergency) regardless of the schedule.
"""

from __future__ import annotations

from datetime import UTC, datetime


def is_entry_allowed(
    *,
    enabled: bool,
    weekend_closed: bool,
    quiet_start_hour_utc: int,
    quiet_end_hour_utc: int,
    now: datetime | None = None,
) -> bool:
    """
    When `enabled` is False, always allow entries.

    When enabled:
      - Saturday/Sunday UTC are blocked if `weekend_closed`.
      - Hours in [quiet_start, quiet_end) UTC are blocked (wraps midnight
        when start > end, e.g. 22→6).
    """
    if not enabled:
        return True

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    else:
        moment = moment.astimezone(UTC)

    # Monday=0 … Sunday=6
    if weekend_closed and moment.weekday() >= 5:
        return False

    start = int(quiet_start_hour_utc) % 24
    end = int(quiet_end_hour_utc) % 24
    hour = moment.hour

    if start == end:
        # Empty quiet window -- nothing blocked by hour.
        return True

    if start < end:
        in_quiet = start <= hour < end
    else:
        # Wraps midnight: e.g. 22:00–06:00
        in_quiet = hour >= start or hour < end

    return not in_quiet


def block_reason(
    *,
    enabled: bool,
    weekend_closed: bool,
    quiet_start_hour_utc: int,
    quiet_end_hour_utc: int,
    now: datetime | None = None,
) -> str | None:
    if is_entry_allowed(
        enabled=enabled,
        weekend_closed=weekend_closed,
        quiet_start_hour_utc=quiet_start_hour_utc,
        quiet_end_hour_utc=quiet_end_hour_utc,
        now=now,
    ):
        return None

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    else:
        moment = moment.astimezone(UTC)

    if weekend_closed and moment.weekday() >= 5:
        return "weekend_closed"
    return "quiet_hours"
