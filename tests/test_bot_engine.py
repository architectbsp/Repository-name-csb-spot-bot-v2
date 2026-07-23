from app.core.bot_engine import BotEngine


def test_bot_engine_creation(monkeypatch):
    # BotEngine builds venues at construct time; use PAPER so tests do not
    # need live API credentials (Sprint 14 REAL gate).
    monkeypatch.setenv("TRADE_MODE", "PAPER")
    monkeypatch.delenv("PAPER_TRADING", raising=False)

    engine = BotEngine()

    assert engine is not None
    assert engine.trading_mode.value == "PAPER"
    assert engine.market_scanner is not None
    assert engine.watch_list is not None
    assert engine.risk_manager is not None
    assert engine.strategy is not None
    assert engine.position_reconciler is not None
    assert engine.retry_policy.backoff_factor() == 2.0
    assert engine.trade_journal.trading_mode == "PAPER"
