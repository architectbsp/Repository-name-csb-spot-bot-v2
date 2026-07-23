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

import httpx

from app.core.security.redact import redact_secrets


logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


def redact_telegram_secrets(text: str, token: str | None = None) -> str:
    """Strip Telegram bot tokens from log / exception strings."""
    known = (token,) if token else None
    return redact_secrets(text, known_secrets=known)


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
        self._updates_offset: int | None = None

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    @property
    def chat_id(self) -> str:
        return self._chat_id

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

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        if not self.configured:
            logger.debug("[TELEGRAM] send skipped -- not configured")
            return False

        if not text:
            return False

        target = (chat_id or self._chat_id).strip()
        if not target:
            return False

        url = f"{_TELEGRAM_API}/bot{self._bot_token}/sendMessage"
        payload: dict = {
            "chat_id": target,
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

    def get_updates(
        self,
        *,
        timeout: int = 0,
        limit: int = 20,
    ) -> list[dict]:
        """
        Long-poll ``getUpdates`` for inbound commands. Failures return []
        so trading never blocks on Telegram.
        """
        if not self.configured:
            return []

        url = f"{_TELEGRAM_API}/bot{self._bot_token}/getUpdates"
        params: dict = {
            "timeout": max(0, int(timeout)),
            "limit": max(1, min(100, int(limit))),
        }
        if self._updates_offset is not None:
            params["offset"] = self._updates_offset

        try:
            response = self._client().get(url, params=params)
            if response.status_code >= 400:
                logger.error(
                    "[TELEGRAM] getUpdates failed status=%s body=%.200s",
                    response.status_code,
                    self._safe(response.text),
                )
                return []
            data = response.json()
            if not data.get("ok", False):
                logger.error(
                    "[TELEGRAM] getUpdates rejected: %s",
                    self._safe(str(data)),
                )
                return []
            updates = list(data.get("result") or [])
            if updates:
                last_id = max(int(u.get("update_id", 0)) for u in updates)
                self._updates_offset = last_id + 1
            return updates
        except Exception as exc:
            logger.error(
                "[TELEGRAM] getUpdates raised type=%s error=%s",
                type(exc).__name__,
                self._safe(str(exc)),
            )
            return []

    def probe_api_reachable(self) -> bool:
        """Cheap reachability check used for 'internet disconnect' alerts."""
        try:
            response = self._client().get(f"{_TELEGRAM_API}/", timeout=5.0)
            return response.status_code < 500
        except Exception:
            return False
