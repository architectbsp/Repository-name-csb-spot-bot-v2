"""
Sprint 13 -- Spot-only + market-order enforcement.

CSB Spot Bot may never touch futures, margin, or derivative venues, and
may never submit limit (or any non-market) orders. Every exchange
adapter, OrderExecution path, and TradeRequest factory routes through
these guards.
"""

from __future__ import annotations

from typing import Any


ORDER_TYPE_MARKET = "market"

# ccxt / venue labels that must never be selected.
_FORBIDDEN_MARKET_TYPES = frozenset(
    {
        "future",
        "futures",
        "swap",
        "margin",
        "cross",
        "isolated",
        "delivery",
        "option",
        "inverse",
        "linear",
        "contract",
        "perpetual",
        "perp",
    }
)

_FORBIDDEN_PARAM_KEYS = frozenset(
    {
        "leverage",
        "reduceonly",
        "reduce_only",
        "hedgemode",
        "hedge_mode",
        "posside",
        "positionside",
        "position_side",
        "tdmode",  # OKX trade mode (futures/margin)
        "margintype",
        "margin_type",
    }
)


class SpotOnlyViolationException(Exception):
    """Raised when a non-spot market or non-market order is attempted."""


def assert_spot_market_type(market_type: str | None = None) -> None:
    """
    Accept only ``spot`` (or unset/empty, which defaults to spot).
    Anything futures/margin/derivative raises ``SpotOnlyViolationException``.
    """
    if market_type is None:
        return
    normalized = str(market_type).strip().lower()
    if not normalized or normalized == "spot":
        return
    if normalized in _FORBIDDEN_MARKET_TYPES or "future" in normalized:
        raise SpotOnlyViolationException(
            f"Spot-only guard: market type '{market_type}' is forbidden"
        )
    # Unknown non-spot labels are also rejected.
    raise SpotOnlyViolationException(
        f"Spot-only guard: unsupported market type '{market_type}'"
    )


def assert_market_order_type(order_type: str | None = None) -> None:
    """Only MARKET orders are allowed (docs/BUSINESS_RULES.md §3 / §10)."""
    if order_type is None:
        return
    normalized = str(order_type).strip().lower().replace("-", "_")
    if normalized in {
        ORDER_TYPE_MARKET,
        "market_buy",
        "market_sell",
        "create_market_buy_order",
        "create_market_sell_order",
    }:
        return
    raise SpotOnlyViolationException(
        f"Market-order guard: order type '{order_type}' is forbidden "
        f"(only '{ORDER_TYPE_MARKET}' is allowed)"
    )


def assert_spot_order_params(params: dict[str, Any] | None = None) -> None:
    """Reject futures/margin-flavoured createOrder params."""
    if not params:
        return
    for key, value in params.items():
        key_l = str(key).strip().lower()
        if key_l in _FORBIDDEN_PARAM_KEYS:
            raise SpotOnlyViolationException(
                f"Spot-only guard: param '{key}' is forbidden on spot orders"
            )
        if key_l in {"type", "defaulttype", "markettype", "market_type"}:
            assert_spot_market_type(value if value is not None else None)


def ensure_spot_ccxt_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Force ``defaultType=spot`` on ccxt client options. Raises if a
    forbidden type was already requested.
    """
    opts = dict(options or {})
    if "defaultType" in opts:
        assert_spot_market_type(opts.get("defaultType"))
    opts["defaultType"] = "spot"
    return opts


def assert_client_is_spot(client: Any) -> None:
    """Inspect a live ccxt client (or duck-typed stand-in) for spot mode."""
    if client is None:
        return
    options = getattr(client, "options", None) or {}
    if isinstance(options, dict):
        assert_spot_market_type(options.get("defaultType", "spot"))
