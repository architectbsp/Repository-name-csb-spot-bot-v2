"""Shared display formatters for the live dashboard panels."""


def money(value: float | None, *, currency: str = "USDT") -> str:
    if value is None:
        return "-"
    return f"{value:,.2f} {currency}"


def money_usd(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def signed_percent(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def signed_money(value: float | None, *, currency: str = "USDT") -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:,.2f} {currency}"


def volume_short(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:g}"


def duration_hms(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def hhmmss(dt) -> str:
    if dt is None:
        return "-"
    return dt.strftime("%H:%M:%S")
