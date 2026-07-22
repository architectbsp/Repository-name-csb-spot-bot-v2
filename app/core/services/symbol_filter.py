"""
Symbol filtering: automatic leveraged-token regex + user blacklist.

Leveraged / inverse tokens (UP, DOWN, 3L, 3S, …) are never tradeable by
this spot bot. Operators can also maintain an explicit blacklist that is
persisted in `symbol_blacklist` and managed from the Settings UI.
"""

from __future__ import annotations

import re

# Base asset ending in these suffixes is treated as a leveraged product
# (e.g. BTCUP, ETHDOWN, SOL3L, DOGE3S, BTCBULL).
_LEVERAGE_SUFFIX_RE = re.compile(
    r"(UP|DOWN|BULL|BEAR|[2-5]L|[2-5]S)$",
    re.IGNORECASE,
)


def base_asset(symbol: str) -> str:
    """`BTC/USDT` → `BTC`; bare `BTCUSDT` → `BTCUSDT` (caller may strip quote)."""
    if "/" in symbol:
        return symbol.split("/", 1)[0].upper()
    return symbol.upper()


def is_leveraged_symbol(symbol: str) -> bool:
    """True for UP/DOWN/3L/3S-style leveraged token symbols."""
    base = base_asset(symbol)
    # Also strip a trailing quote glued without slash (BTCUPUSDT).
    for quote in ("USDT", "USDC", "USD", "BUSD"):
        if base.endswith(quote) and len(base) > len(quote):
            base = base[: -len(quote)]
            break
    return bool(_LEVERAGE_SUFFIX_RE.search(base))


def normalize_blacklist_symbol(symbol: str) -> str:
    """Store blacklist keys as uppercase full symbols when possible."""
    return symbol.strip().upper()


class SymbolFilter:
    """
    Combines automatic leverage regex with an in-memory + persisted
    user blacklist. MarketScanner calls `is_blocked()` during filter_symbols.
    """

    def __init__(self) -> None:
        self._blacklist: set[str] = set()
        self._repository = None

    def set_repository(self, repository) -> None:
        self._repository = repository
        self.reload()

    def reload(self) -> None:
        if self._repository is None:
            return
        self._blacklist = {
            normalize_blacklist_symbol(row.symbol)
            for row in self._repository.list_all()
        }

    def list_blacklist(self) -> list[str]:
        return sorted(self._blacklist)

    def add(self, symbol: str, note: str | None = None) -> str:
        key = normalize_blacklist_symbol(symbol)
        if not key:
            raise ValueError("Sembol boş olamaz")
        self._blacklist.add(key)
        if self._repository is not None:
            self._repository.add(key, note=note)
        return key

    def remove(self, symbol: str) -> bool:
        key = normalize_blacklist_symbol(symbol)
        existed = key in self._blacklist
        self._blacklist.discard(key)
        if self._repository is not None:
            self._repository.remove(key)
        return existed

    def is_blacklisted(self, symbol: str) -> bool:
        key = normalize_blacklist_symbol(symbol)
        if key in self._blacklist:
            return True
        # Also match by base (blacklist "BTCUP" blocks "BTCUP/USDT").
        base = base_asset(symbol)
        return base in self._blacklist or normalize_blacklist_symbol(base) in self._blacklist

    def is_blocked(self, symbol: str) -> bool:
        return is_leveraged_symbol(symbol) or self.is_blacklisted(symbol)

    def block_reason(self, symbol: str) -> str | None:
        if is_leveraged_symbol(symbol):
            return "leveraged_token"
        if self.is_blacklisted(symbol):
            return "blacklist"
        return None
