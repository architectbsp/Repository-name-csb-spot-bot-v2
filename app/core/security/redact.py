"""
R6 -- secret redaction for logs, exceptions, and diagnostics.

Keeps credentials out of log lines, stored error strings, and health
payloads without changing trading behavior.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable


# Telegram Bot API embeds the token in the URL path.
_TELEGRAM_BOT_URL_RE = re.compile(
    r"(https?://api\.telegram\.org/bot)([^/\s\"']+)(/?)",
    re.IGNORECASE,
)

# Signed REST query params / form fields commonly echoed by ccxt errors.
_QUERY_SECRET_RE = re.compile(
    r"(?i)\b("
    r"signature|api[_-]?key|api[_-]?secret|secret|password|passphrase|"
    r"access[_-]?token|refresh[_-]?token|private[_-]?key|bot[_-]?token"
    r")\s*=\s*([^\s&\"']+)"
)

_JSON_SECRET_RE = re.compile(
    r'(?i)("(?:'
    r"apiKey|api_key|apiSecret|api_secret|secret|password|passphrase|"
    r"access_token|refresh_token|bot_token|Authorization"
    r')"\s*:\s*")([^"]*)(")'
)

_BEARER_RE = re.compile(r"(?i)(Authorization:\s*Bearer\s+)(\S+)")

# postgres/mysql URLs: scheme://user:password@host
_DB_URL_RE = re.compile(
    r"(?i)\b([a-z0-9+.-]+://[^:/\s]+:)([^@/\s]+)(@)"
)


def redact_secrets(
    text: str | None,
    *,
    known_secrets: Iterable[str] | None = None,
) -> str:
    """
    Return ``text`` with credentials replaced by ``***``.

    Safe for empty/None (returns empty string for None).
    """
    if text is None:
        return ""
    if not text:
        return text

    redacted = text
    if known_secrets:
        for secret in known_secrets:
            if secret and secret in redacted:
                redacted = redacted.replace(secret, "***")

    redacted = _TELEGRAM_BOT_URL_RE.sub(r"\1***\3", redacted)
    redacted = _BEARER_RE.sub(r"\1***", redacted)
    redacted = _QUERY_SECRET_RE.sub(r"\1=***", redacted)
    redacted = _JSON_SECRET_RE.sub(r"\1***\3", redacted)
    redacted = _DB_URL_RE.sub(r"\1***\3", redacted)
    return redacted


def safe_error_text(exc: BaseException | None) -> str:
    """Type + message suitable for logs/health, with secrets stripped."""
    if exc is None:
        return ""
    return redact_secrets(f"{type(exc).__name__}: {exc}")


def safe_exc_message(exc: BaseException | None) -> str:
    """Exception message only (no type prefix), redacted."""
    if exc is None:
        return ""
    return redact_secrets(str(exc))


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts secrets from the final log line."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))
