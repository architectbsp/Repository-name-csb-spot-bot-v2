"""
Trading Hours / Time Constraints (Sprint 10).

Default: OFF -- bot trades 7/24. When ``trading_hours_enabled`` is True,
only **new BUY entries** are gated by the active UTC window and optional
weekend lock. Stop loss, trailing, partial TP, and emergency exits are
never gated by this module.

Aliases: ``TimeConstraintService`` / ``TradingHoursManager``.
"""

from __future__ import annotations

from datetime import UTC, datetime, time


DEFAULT_TRADING_START = "08:00"
DEFAULT_TRADING_END = "23:00"


def parse_hhmm(raw: str | None, *, fallback: str) -> time:
    """Parse ``HH:MM`` or ``H:MM``; invalid values fall back to ``fallback``."""
    text = (raw or "").strip() or fallback
    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("out of range")
        return time(hour=hour, minute=minute)
    except (TypeError, ValueError, IndexError):
        fb = fallback.split(":")
        return time(hour=int(fb[0]), minute=int(fb[1]) if len(fb) > 1 else 0)


def _minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def _coerce_now(now: datetime | None) -> datetime:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _resolve_weekend_flag(
    *,
    disable_weekend_trading: bool | None,
    weekend_closed: bool | None,
) -> bool:
    """Prefer Sprint 10 ``disable_weekend_trading``; fall back to legacy."""
    if disable_weekend_trading is not None:
        return bool(disable_weekend_trading)
    if weekend_closed is not None:
        return bool(weekend_closed)
    return False


def is_entry_allowed(
    *,
    enabled: bool,
    trading_start_time: str = DEFAULT_TRADING_START,
    trading_end_time: str = DEFAULT_TRADING_END,
    disable_weekend_trading: bool | None = None,
    # Legacy kwargs (quiet window / weekend_closed) -- still accepted.
    weekend_closed: bool | None = None,
    quiet_start_hour_utc: int | None = None,
    quiet_end_hour_utc: int | None = None,
    now: datetime | None = None,
) -> bool:
    """
    When ``enabled`` is False, always allow entries (7/24).

    When enabled:
      - Saturday/Sunday UTC blocked if ``disable_weekend_trading``.
      - Entries allowed only inside the active UTC window
        ``[trading_start_time, trading_end_time)`` (wraps midnight when
        start > end). Equal start/end means no hour filter.
      - If only legacy quiet_* hours are supplied (no start/end override
        from callers that still use the old API), the quiet window is
        treated as the *blocked* interval (inverted active window).
    """
    if not enabled:
        return True

    moment = _coerce_now(now)
    weekend_block = _resolve_weekend_flag(
        disable_weekend_trading=disable_weekend_trading,
        weekend_closed=weekend_closed,
    )
    if weekend_block and moment.weekday() >= 5:
        return False

    # Legacy quiet-window path when callers pass quiet_* explicitly and
    # did not intend the Sprint 10 active-window API (detected by the
    # quiet kwargs being non-None while start/end stay at defaults from
    # positional-less calls that still pass quiet_*).
    if quiet_start_hour_utc is not None and quiet_end_hour_utc is not None:
        return _allowed_outside_quiet(
            moment,
            int(quiet_start_hour_utc),
            int(quiet_end_hour_utc),
        )

    start = parse_hhmm(trading_start_time, fallback=DEFAULT_TRADING_START)
    end = parse_hhmm(trading_end_time, fallback=DEFAULT_TRADING_END)
    return _allowed_inside_active(moment, start, end)


def _allowed_outside_quiet(
    moment: datetime,
    quiet_start_hour_utc: int,
    quiet_end_hour_utc: int,
) -> bool:
    start = int(quiet_start_hour_utc) % 24
    end = int(quiet_end_hour_utc) % 24
    hour = moment.hour
    if start == end:
        return True
    if start < end:
        in_quiet = start <= hour < end
    else:
        in_quiet = hour >= start or hour < end
    return not in_quiet


def _allowed_inside_active(
    moment: datetime,
    start: time,
    end: time,
) -> bool:
    start_m = _minutes_since_midnight(start)
    end_m = _minutes_since_midnight(end)
    now_m = moment.hour * 60 + moment.minute
    if start_m == end_m:
        return True
    if start_m < end_m:
        return start_m <= now_m < end_m
    # Wraps midnight: e.g. 22:00–06:00 active
    return now_m >= start_m or now_m < end_m


def block_reason(
    *,
    enabled: bool,
    trading_start_time: str = DEFAULT_TRADING_START,
    trading_end_time: str = DEFAULT_TRADING_END,
    disable_weekend_trading: bool | None = None,
    weekend_closed: bool | None = None,
    quiet_start_hour_utc: int | None = None,
    quiet_end_hour_utc: int | None = None,
    now: datetime | None = None,
) -> str | None:
    if is_entry_allowed(
        enabled=enabled,
        trading_start_time=trading_start_time,
        trading_end_time=trading_end_time,
        disable_weekend_trading=disable_weekend_trading,
        weekend_closed=weekend_closed,
        quiet_start_hour_utc=quiet_start_hour_utc,
        quiet_end_hour_utc=quiet_end_hour_utc,
        now=now,
    ):
        return None

    moment = _coerce_now(now)
    weekend_block = _resolve_weekend_flag(
        disable_weekend_trading=disable_weekend_trading,
        weekend_closed=weekend_closed,
    )
    if weekend_block and moment.weekday() >= 5:
        return "weekend_closed"

    if quiet_start_hour_utc is not None and quiet_end_hour_utc is not None:
        return "quiet_hours"
    return "outside_trading_hours"


class TimeConstraintService:
    """
    Settings-backed entry gate. Wire once; ``config.updated`` is live via
    shared AppSettings (no local cache).
    """

    def __init__(self, config=None) -> None:
        self._config = config

    def set_config(self, config) -> None:
        self._config = config

    def on_config_updated(self, event) -> None:
        """Live reload -- knobs are read from shared AppSettings each call."""
        return None

    def is_entry_allowed(self, now: datetime | None = None) -> bool:
        return is_entry_allowed(**self._kwargs_from_config(), now=now)

    def block_reason(self, now: datetime | None = None) -> str | None:
        return block_reason(**self._kwargs_from_config(), now=now)

    def _kwargs_from_config(self) -> dict:
        strategy = getattr(self._config, "strategy", None)
        if strategy is None:
            return {
                "enabled": False,
                "disable_weekend_trading": False,
                "trading_start_time": DEFAULT_TRADING_START,
                "trading_end_time": DEFAULT_TRADING_END,
            }

        disable_weekend = getattr(strategy, "disable_weekend_trading", None)
        if disable_weekend is None:
            disable_weekend = getattr(strategy, "weekend_closed", 0)

        return {
            "enabled": bool(int(getattr(strategy, "trading_hours_enabled", 0) or 0)),
            "disable_weekend_trading": bool(int(disable_weekend or 0)),
            "trading_start_time": str(
                getattr(strategy, "trading_start_time", DEFAULT_TRADING_START)
                or DEFAULT_TRADING_START
            ),
            "trading_end_time": str(
                getattr(strategy, "trading_end_time", DEFAULT_TRADING_END)
                or DEFAULT_TRADING_END
            ),
        }


# Sprint 10 naming alias.
TradingHoursManager = TimeConstraintService
