"""R6 -- secret redaction coverage."""

from app.core.config.settings import ExchangeSettings, TelegramSettings
from app.core.security.redact import redact_secrets, safe_error_text, safe_exc_message


def test_redact_signature_and_api_key_query_params():
    raw = (
        "binance GET https://api.binance.com/api/v3/order"
        "?symbol=BTCUSDT&apiKey=LIVEKEY123&signature=abcdef0123456789"
    )
    safe = redact_secrets(raw)
    assert "LIVEKEY123" not in safe
    assert "abcdef0123456789" not in safe
    assert "apiKey=***" in safe
    assert "signature=***" in safe


def test_redact_telegram_bot_url_and_known_token():
    token = "123456:ABC-DEF"
    raw = f"https://api.telegram.org/bot{token}/sendMessage failed"
    safe = redact_secrets(raw, known_secrets=[token])
    assert token not in safe
    assert "bot***/" in safe or "bot***" in safe


def test_redact_db_url_password():
    raw = "postgresql://user:SuperSecretPass@localhost:5432/csb"
    safe = redact_secrets(raw)
    assert "SuperSecretPass" not in safe
    assert "user:***@" in safe


def test_safe_error_text_redacts_exception_message():
    exc = RuntimeError("request failed signature=deadbeef apiKey=ZZZ")
    text = safe_error_text(exc)
    assert "deadbeef" not in text
    assert "ZZZ" not in text
    assert "RuntimeError" in text


def test_exchange_settings_repr_masks_credentials():
    settings = ExchangeSettings(
        exchange="binance",
        api_key="REAL_KEY",
        api_secret="REAL_SECRET",
        passphrase="REAL_PASS",
        testnet=True,
    )
    text = repr(settings)
    assert "REAL_KEY" not in text
    assert "REAL_SECRET" not in text
    assert "REAL_PASS" not in text
    assert "***" in text


def test_telegram_settings_repr_masks_token():
    settings = TelegramSettings(
        bot_token="123:TOKEN",
        chat_id="1",
        admin_chat_id="1",
        enabled=True,
    )
    text = repr(settings)
    assert "123:TOKEN" not in text
    assert "***" in text


def test_safe_exc_message_empty_for_none():
    assert safe_exc_message(None) == ""
