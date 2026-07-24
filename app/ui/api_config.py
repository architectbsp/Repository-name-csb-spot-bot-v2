"""
API Configuration — per-exchange credential isolation.

Each supported venue owns an independent draft object, validation error,
and .env key namespace. Dialog UI must copy values in/out of these drafts;
it must never bind multiple exchanges to one shared mutable model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def exchange_env_names(exchange_name: str) -> tuple[str, str, str, str]:
    prefix = exchange_name.strip().upper()
    return (
        f"{prefix}_API_KEY",
        f"{prefix}_API_SECRET",
        f"{prefix}_PASSPHRASE",
        f"{prefix}_TESTNET",
    )


def requires_passphrase(exchange_name: str) -> bool:
    return exchange_name.strip().lower() == "okx"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        raw = row.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def persist_env_values(path: Path, values: dict[str, str]) -> None:
    """Merge ``values`` into ``path`` without removing unrelated keys."""
    existing: list[str] = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8").splitlines()

    key_to_index: dict[str, int] = {}
    for index, line in enumerate(existing):
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key = raw.split("=", 1)[0].strip()
        if key:
            key_to_index[key] = index

    for key, value in values.items():
        rendered = f"{key}={value}"
        if key in key_to_index:
            existing[key_to_index[key]] = rendered
        else:
            existing.append(rendered)

    path.write_text("\n".join(existing).rstrip() + "\n", encoding="utf-8")


@dataclass(slots=True)
class ExchangeCredentialDraft:
    """Independent credential + validation state for exactly one exchange."""

    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    testnet: bool = True
    validation_error: str | None = None


class ExchangeCredentialsSession:
    """
    In-memory session of per-exchange drafts loaded from / saved to ``.env``.

    Guarantees: each exchange name maps to its own ``ExchangeCredentialDraft``
    instance; updates and validation never mutate another exchange's draft.
    """

    def __init__(self, env_path: Path, exchanges: list[str]) -> None:
        self._env_path = Path(env_path)
        # Fresh independent objects — never alias drafts across keys.
        self._drafts: dict[str, ExchangeCredentialDraft] = {
            name.strip().lower(): ExchangeCredentialDraft()
            for name in exchanges
            if name.strip()
        }
        self.reload_from_disk()

    @property
    def exchanges(self) -> list[str]:
        return sorted(self._drafts.keys())

    def draft(self, exchange: str) -> ExchangeCredentialDraft:
        key = exchange.strip().lower()
        if key not in self._drafts:
            raise KeyError(f"Unsupported exchange: {exchange!r}")
        return self._drafts[key]

    def snapshot(self, exchange: str) -> ExchangeCredentialDraft:
        """Return a new draft copy (no shared reference)."""
        src = self.draft(exchange)
        return ExchangeCredentialDraft(
            api_key=src.api_key,
            api_secret=src.api_secret,
            passphrase=src.passphrase,
            testnet=src.testnet,
            validation_error=src.validation_error,
        )

    def reload_from_disk(self) -> None:
        env_values = read_env_file(self._env_path)
        global_testnet = _as_bool(
            env_values.get("EXCHANGE_TESTNET", "true"),
            default=True,
        )
        for name, draft in self._drafts.items():
            key_name, secret_name, passphrase_name, testnet_name = exchange_env_names(
                name
            )
            draft.api_key = env_values.get(key_name, "")
            draft.api_secret = env_values.get(secret_name, "")
            draft.passphrase = env_values.get(passphrase_name, "")
            if testnet_name in env_values:
                draft.testnet = _as_bool(env_values[testnet_name], default=True)
            else:
                draft.testnet = global_testnet
            draft.validation_error = None

    def capture(
        self,
        exchange: str,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        testnet: bool,
    ) -> None:
        """Write UI field values into exactly one exchange draft."""
        draft = self.draft(exchange)
        draft.api_key = (api_key or "").strip()
        draft.api_secret = (api_secret or "").strip()
        draft.passphrase = (passphrase or "").strip()
        draft.testnet = bool(testnet)
        # Editing clears that exchange's prior validation only.
        draft.validation_error = None

    def validate(self, exchange: str) -> str | None:
        """Validate one exchange; leave all other drafts untouched."""
        name = exchange.strip().lower()
        draft = self.draft(name)
        label = name.upper()
        if not draft.api_key:
            draft.validation_error = f"{label}: API Key gerekli."
        elif not draft.api_secret:
            draft.validation_error = f"{label}: API Secret gerekli."
        elif requires_passphrase(name) and not draft.passphrase:
            draft.validation_error = f"{label}: Passphrase gerekli."
        else:
            draft.validation_error = None
        return draft.validation_error

    def persist(self, exchange: str) -> None:
        """
        Persist only ``exchange`` credentials into ``.env``.

        Never overwrites another venue's ``*_API_KEY`` / secret / passphrase.
        """
        name = exchange.strip().lower()
        draft = self.draft(name)
        key_name, secret_name, passphrase_name, testnet_name = exchange_env_names(name)
        payload: dict[str, str] = {
            "EXCHANGE": name,
            "EXCHANGE_TESTNET": "true" if draft.testnet else "false",
            key_name: draft.api_key,
            secret_name: draft.api_secret,
            testnet_name: "true" if draft.testnet else "false",
        }
        if requires_passphrase(name):
            payload[passphrase_name] = draft.passphrase
        persist_env_values(self._env_path, payload)


def _as_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
