"""Per-exchange API credential isolation (TASK-01)."""

from __future__ import annotations

from pathlib import Path

from app.ui.api_config import (
    ExchangeCredentialDraft,
    ExchangeCredentialsSession,
    exchange_env_names,
    persist_env_values,
    read_env_file,
    requires_passphrase,
)


SUPPORTED = ["binance", "bybit", "okx", "kraken", "mexc"]


def test_each_exchange_owns_independent_draft_instances(tmp_path: Path):
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    drafts = [session.draft(name) for name in SUPPORTED]
    assert len({id(d) for d in drafts}) == len(SUPPORTED)


def test_editing_one_exchange_never_mutates_another(tmp_path: Path):
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    session.capture(
        "binance",
        api_key="bin-key",
        api_secret="bin-secret",
        passphrase="",
        testnet=True,
    )
    session.capture(
        "bybit",
        api_key="byb-key",
        api_secret="byb-secret",
        passphrase="",
        testnet=False,
    )

    session.capture(
        "binance",
        api_key="bin-key-2",
        api_secret="bin-secret-2",
        passphrase="",
        testnet=True,
    )

    assert session.draft("binance").api_key == "bin-key-2"
    assert session.draft("bybit").api_key == "byb-key"
    assert session.draft("bybit").api_secret == "byb-secret"
    assert session.draft("okx").api_key == ""
    assert session.draft("kraken").api_key == ""
    assert session.draft("mexc").api_key == ""


def test_switch_roundtrip_keeps_unsaved_drafts(tmp_path: Path):
    """Simulate dialog switch: capture A → capture B → re-read A."""
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    session.capture(
        "binance",
        api_key="AAA",
        api_secret="aaa",
        passphrase="",
        testnet=True,
    )
    session.capture(
        "bybit",
        api_key="BBB",
        api_secret="bbb",
        passphrase="",
        testnet=True,
    )
    snap = session.snapshot("binance")
    assert snap.api_key == "AAA"
    assert snap.api_secret == "aaa"
    # snapshot is a copy, not the live object
    assert snap is not session.draft("binance")


def test_persist_binance_does_not_overwrite_bybit(tmp_path: Path):
    env_path = tmp_path / ".env"
    session = ExchangeCredentialsSession(env_path, SUPPORTED)
    session.capture(
        "binance",
        api_key="bin-k",
        api_secret="bin-s",
        passphrase="",
        testnet=True,
    )
    session.capture(
        "bybit",
        api_key="byb-k",
        api_secret="byb-s",
        passphrase="",
        testnet=False,
    )
    session.persist("binance")
    session.persist("bybit")

    # Mutate and re-save only binance
    session.capture(
        "binance",
        api_key="bin-k-new",
        api_secret="bin-s-new",
        passphrase="",
        testnet=True,
    )
    session.persist("binance")

    values = read_env_file(env_path)
    assert values["BINANCE_API_KEY"] == "bin-k-new"
    assert values["BINANCE_API_SECRET"] == "bin-s-new"
    assert values["BYBIT_API_KEY"] == "byb-k"
    assert values["BYBIT_API_SECRET"] == "byb-s"
    assert "BYBIT_PASSPHRASE" not in values


def test_persist_okx_writes_passphrase_only_for_okx(tmp_path: Path):
    env_path = tmp_path / ".env"
    session = ExchangeCredentialsSession(env_path, SUPPORTED)
    session.capture(
        "okx",
        api_key="okx-k",
        api_secret="okx-s",
        passphrase="okx-p",
        testnet=True,
    )
    session.persist("okx")
    session.capture(
        "kraken",
        api_key="kr-k",
        api_secret="kr-s",
        passphrase="should-not-persist",
        testnet=True,
    )
    session.persist("kraken")

    values = read_env_file(env_path)
    assert values["OKX_PASSPHRASE"] == "okx-p"
    assert "KRAKEN_PASSPHRASE" not in values


def test_reload_from_disk_restores_each_exchange(tmp_path: Path):
    env_path = tmp_path / ".env"
    persist_env_values(
        env_path,
        {
            "BINANCE_API_KEY": "b1",
            "BINANCE_API_SECRET": "bs1",
            "BINANCE_TESTNET": "true",
            "MEXC_API_KEY": "m1",
            "MEXC_API_SECRET": "ms1",
            "MEXC_TESTNET": "false",
            "OKX_API_KEY": "o1",
            "OKX_API_SECRET": "os1",
            "OKX_PASSPHRASE": "op1",
            "OKX_TESTNET": "true",
        },
    )
    session = ExchangeCredentialsSession(env_path, SUPPORTED)
    assert session.draft("binance").api_key == "b1"
    assert session.draft("mexc").api_key == "m1"
    assert session.draft("mexc").testnet is False
    assert session.draft("okx").passphrase == "op1"
    assert session.draft("bybit").api_key == ""
    assert session.draft("kraken").api_key == ""


def test_validation_is_exchange_specific(tmp_path: Path):
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    session.capture(
        "bybit",
        api_key="ok",
        api_secret="ok",
        passphrase="",
        testnet=True,
    )
    err = session.validate("binance")
    assert err is not None
    assert "BINANCE" in err
    assert session.draft("bybit").validation_error is None
    assert session.validate("bybit") is None
    assert session.draft("binance").validation_error is not None


def test_okx_validation_requires_passphrase(tmp_path: Path):
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    session.capture(
        "okx",
        api_key="k",
        api_secret="s",
        passphrase="",
        testnet=True,
    )
    assert session.validate("okx") is not None
    session.capture(
        "okx",
        api_key="k",
        api_secret="s",
        passphrase="p",
        testnet=True,
    )
    assert session.validate("okx") is None


def test_requires_passphrase_only_okx():
    assert requires_passphrase("okx") is True
    assert requires_passphrase("binance") is False
    assert exchange_env_names("binance")[0] == "BINANCE_API_KEY"


def test_draft_objects_are_not_shared_via_snapshot(tmp_path: Path):
    session = ExchangeCredentialsSession(tmp_path / ".env", SUPPORTED)
    session.capture(
        "kraken",
        api_key="k",
        api_secret="s",
        passphrase="",
        testnet=True,
    )
    a = session.snapshot("kraken")
    b = session.snapshot("kraken")
    assert a is not b
    assert isinstance(a, ExchangeCredentialDraft)
    a.api_key = "mutated"
    assert session.draft("kraken").api_key == "k"
