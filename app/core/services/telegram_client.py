"""
Sprint 11 -- thin Telegram Bot API client.

Uses httpx (already pinned) to call `sendMessage`. Never raises into
trading paths: every failure is logged and returned as False so a
Telegram outage cannot break order flow.

Logging never includes the bot token: URLs embed `/bot<token>/` and
httpx exceptions often echo the request URL, so every log path runs
through ``redact_telegram_secrets``.
"""

from __future__ import annotations

import logging
import re

import httpx


logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"

# Matches https://api.telegram.org/bot<TOKEN>/... in exception/log text.
_BOT_URL_RE = re.compile(
    r"(https?://api\.telegram\.org/bot)([^/\s\"']+)(/?)",
    re.IGNORECASE,
)


def redact_telegram_secrets(text: str, token: str | None = None) -> str:
    """Strip Telegram bot tokens from log / exception strings."""
    if not text:
        return text
    redacted = text
    if token:
        redacted = redacted.replace(token, "***")
    return _BOT_URL_RE.sub(r"\1***\3", redacted)


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._timeout = timeout_seconds
        self._http = http_client
        self._owns_http = http_client is None

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self._timeout)
        return self._http

    def _safe(self, text: str) -> str:
        return redact_telegram_secrets(text, self._bot_token)

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()
            self._http = None

    def send_message(self, text: str, *, parse_mode: str | None = None) -> bool:
        if not self.configured:
            logger.debug("[TELEGRAM] send skipped -- not configured")
            return False

        if not text:
            return False

        url = f"{_TELEGRAM_API}/bot{self._bot_token}/sendMessage"
        payload: dict = {
            "chat_id": self._chat_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            response = self._client().post(url, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "[TELEGRAM] sendMessage failed status=%s body=%.200s",
                    response.status_code,
                    self._safe(response.text),
                )
                return False
            data = response.json()
            if not data.get("ok", False):
                logger.error(
                    "[TELEGRAM] sendMessage rejected: %s",
                    self._safe(str(data)),
                )
                return False
            return True
        except Exception as exc:
            # Never logger.exception here: httpx often embeds the full
            # request URL (with token) in the exception message / repr.
            logger.error(
                "[TELEGRAM] sendMessage raised type=%s error=%s",
                type(exc).__name__,
                self._safe(str(exc)),
            )
            return False

    def probe_api_reachable(self) -> bool:
        """Cheap reachability check used for 'internet disconnect' alerts."""
        try:
            response = self._client().get(f"{_TELEGRAM_API}/", timeout=5.0)
            return response.status_code < 500
        except Exception:
            return False
