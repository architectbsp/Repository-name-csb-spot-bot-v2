"""
Sprint 14 -- trading mode isolation: PAPER vs REAL.

PAPER (aliases: paper, paper_trading, sim, simulation):
  Real market-data may be used for prices, but balance / order endpoints
  on the live venue must never be hit -- fills stay on the local paper
  wallet (PaperExchangeAdapter).

REAL (aliases: real, live, production, prod):
  Live spot MARKET orders. Requires non-empty API key + secret
  (and passphrase for OKX) before the venue adapter is built.
"""

from __future__ import annotations

import os
from enum import Enum

from app.core.config.settings import ExchangeSettings


class TradingMode(str, Enum):
    PAPER = "PAPER"
    REAL = "REAL"


_PAPER_ALIASES = frozenset(
    {"paper", "paper_trading", "sim", "simulation"}
)
_REAL_ALIASES = frozenset({"real", "live", "production", "prod"})


class MissingRealCredentialsError(ValueError):
    """Raised when REAL mode is selected without API credentials."""


def normalize_trading_mode(value: str | TradingMode | None) -> TradingMode:
    if isinstance(value, TradingMode):
        return value
    if value is None:
        return TradingMode.REAL
    key = str(value).strip().lower()
    if key in _PAPER_ALIASES:
        return TradingMode.PAPER
    if key in _REAL_ALIASES:
        return TradingMode.REAL
    raise ValueError(
        f"Unknown trading mode {value!r}. Use PAPER or REAL "
        f"(aliases: paper/sim, real/live/production)."
    )


def resolve_trading_mode() -> TradingMode:
    """
    Resolve process trading mode from env.

    Precedence:
      1. ``TRADE_MODE`` / ``TRADING_MODE`` when set to a known alias
      2. ``PAPER_TRADING`` truthy → PAPER
      3. Default → REAL
    """
    for name in ("TRADE_MODE", "TRADING_MODE"):
        raw = (os.getenv(name) or "").strip()
        if raw:
            key = raw.lower()
            if key in _PAPER_ALIASES or key in _REAL_ALIASES:
                return normalize_trading_mode(key)
            raise ValueError(
                f"Invalid {name}={raw!r}. Expected PAPER|REAL "
                f"(or paper/live aliases)."
            )

    flag = (os.getenv("PAPER_TRADING") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return TradingMode.PAPER
    return TradingMode.REAL


def paper_trading_enabled() -> bool:
    """Backward-compatible helper used by the exchange factory."""
    return resolve_trading_mode() is TradingMode.PAPER


def require_real_api_credentials(settings: ExchangeSettings) -> None:
    """
    REAL mode gate: refuse to build a live trading adapter without keys.
    Public market-data wrappers in PAPER mode are unaffected.
    """
    key = (settings.api_key or "").strip()
    secret = (settings.api_secret or "").strip()
    if not key or not secret:
        raise MissingRealCredentialsError(
            "REAL trading mode requires non-empty API key and secret "
            f"for exchange={settings.exchange!r} "
            "(set EXCHANGE_API_KEY / EXCHANGE_API_SECRET or per-venue "
            "BINANCE_API_KEY / …)."
        )

    if (settings.exchange or "").strip().lower() == "okx":
        passphrase = (settings.passphrase or "").strip()
        if not passphrase:
            raise MissingRealCredentialsError(
                "REAL trading mode on OKX also requires EXCHANGE_PASSPHRASE "
                "(or OKX_PASSPHRASE)."
            )


def mode_badge(mode: TradingMode | str | None) -> str:
    """Short label for UI / Telegram (always PAPER or REAL)."""
    return normalize_trading_mode(mode).value
