from app.core.bot_engine import BotEngine


def test_bot_engine_creation():
    engine = BotEngine()

    assert engine is not None
    assert engine.market_scanner is not None
    assert engine.watch_list is not None
    assert engine.risk_manager is not None
    assert engine.strategy is not None
