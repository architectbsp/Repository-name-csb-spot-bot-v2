"""
Symbol filtering: leveraged-token regex + operator blacklist + Settings patterns.

Sources (OR-combined -- any match blocks the symbol):

1. Built-in leverage suffix check (UP / DOWN / BULL / BEAR / 2L–5L / 2S–5S).
2. Configurable ``filtered_patterns`` (comma-separated regexes from Settings).
3. Exact-match blacklist from the ``symbol_blacklist`` table (Settings UI card)
   union Settings ``blacklist_symbols`` (comma-separated).

MarketScanner drops blocked symbols in ``filter_symbols``; RiskManager also
refuses BUY even if a signal slips through. ``config.updated`` reloads the
Settings-driven lists without a restart.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Base asset ending in these suffixes is treated as a leveraged product
# (e.g. BTCUP, ETHDOWN, SOL3L, DOGE3S, BTCBULL).
_LEVERAGE_SUFFIX_RE = re.compile(
    r"(UP|DOWN|BULL|BEAR|[2-5]L|[2-5]S)$",
    re.IGNORECASE,
)

# Sprint 9 defaults for Settings ``filtered_patterns`` (CSV of regexes).
# Matched against slash and compact symbol forms (see ``_symbol_match_forms``).
DEFAULT_FILTERED_PATTERNS = (
    ".*UPUSDT$,.*DOWNUSDT$,.*3LUSDT$,.*3SUSDT$,BEAR.*,BULL.*"
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


def parse_csv_tokens(raw: str | None) -> list[str]:
    """Split a Settings CSV (commas or semicolons) into non-empty tokens."""
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts


def _symbol_match_forms(symbol: str) -> tuple[str, ...]:
    """Forms used for exact + regex matching (slash, compact, base)."""
    key = normalize_blacklist_symbol(symbol)
    compact = key.replace("/", "")
    base = base_asset(symbol)
    forms = {key, compact, base, normalize_blacklist_symbol(base)}
    return tuple(sorted(forms))


def compile_filtered_patterns(raw: str | None) -> list[re.Pattern[str]]:
    """Compile comma-separated regexes; skip invalid patterns with a warning."""
    compiled: list[re.Pattern[str]] = []
    for token in parse_csv_tokens(raw):
        try:
            compiled.append(re.compile(token, re.IGNORECASE))
        except re.error as exc:
            logger.warning(
                "[SymbolFilter] invalid filtered_patterns regex %r: %s",
                token,
                exc,
            )
    return compiled


class SymbolFilter:
    """
    Combines built-in leverage regex, Settings patterns, and an exact-match
    blacklist (DB table + Settings CSV). MarketScanner / RiskManager call
    ``is_blocked()``.
    """

    def __init__(self) -> None:
        self._blacklist: set[str] = set()
        self._settings_blacklist: set[str] = set()
        self._pattern_res: list[re.Pattern[str]] = compile_filtered_patterns(
            DEFAULT_FILTERED_PATTERNS
        )
        self._repository = None
        self._config = None

    def set_repository(self, repository) -> None:
        self._repository = repository
        self.reload()

    def set_config(self, config) -> None:
        self._config = config
        self.apply_from_config(config)

    def on_config_updated(self, event) -> None:
        """EventBus ``config.updated`` -- pick up blacklist_symbols / patterns."""
        values = getattr(event, "values", None)
        if isinstance(values, dict) and values:
            # Full snapshot from ConfigManager.save -- apply both knobs.
            self.apply_from_values(values)
            return
        config = getattr(event, "settings", None) or self._config
        if config is not None:
            self._config = config
            self.apply_from_config(config)

    def apply_from_config(self, config) -> None:
        strategy = getattr(config, "strategy", None)
        if strategy is None:
            return
        self.apply_from_values(
            {
                "blacklist_symbols": getattr(strategy, "blacklist_symbols", ""),
                "filtered_patterns": getattr(
                    strategy,
                    "filtered_patterns",
                    DEFAULT_FILTERED_PATTERNS,
                ),
            }
        )

    def apply_from_values(self, values: dict) -> None:
        if "blacklist_symbols" in values:
            self._settings_blacklist = {
                normalize_blacklist_symbol(token)
                for token in parse_csv_tokens(values.get("blacklist_symbols"))
            }
        if "filtered_patterns" in values:
            raw = values.get("filtered_patterns")
            # Empty string means "no extra Settings patterns" (built-in
            # leverage check still applies). None keeps prior patterns.
            if raw is None:
                return
            self._pattern_res = compile_filtered_patterns(str(raw))

    def reload(self) -> None:
        if self._repository is None:
            return
        self._blacklist = {
            normalize_blacklist_symbol(row.symbol)
            for row in self._repository.list_all()
        }

    def list_blacklist(self) -> list[str]:
        return sorted(self._blacklist | self._settings_blacklist)

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
        combined = self._blacklist | self._settings_blacklist
        if not combined:
            return False
        forms = set(_symbol_match_forms(symbol))
        if forms & combined:
            return True
        compact_keys = {key.replace("/", "") for key in combined}
        if forms & compact_keys:
            return True
        base = base_asset(symbol)
        if base in combined or normalize_blacklist_symbol(base) in combined:
            return True
        return any(base_asset(key) == base for key in combined)

    def matches_filtered_pattern(self, symbol: str) -> bool:
        forms = _symbol_match_forms(symbol)
        for pattern in self._pattern_res:
            for form in forms:
                if pattern.search(form):
                    return True
        return False

    def is_blocked(self, symbol: str) -> bool:
        return (
            is_leveraged_symbol(symbol)
            or self.matches_filtered_pattern(symbol)
            or self.is_blacklisted(symbol)
        )

    def block_reason(self, symbol: str) -> str | None:
        if is_leveraged_symbol(symbol):
            return "leveraged_token"
        if self.matches_filtered_pattern(symbol):
            return "filtered_pattern"
        if self.is_blacklisted(symbol):
            return "blacklist"
        return None


# Sprint 9 naming alias -- same engine.
BlacklistManager = SymbolFilter
