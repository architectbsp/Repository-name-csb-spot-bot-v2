from app.core.state.state import CoinState


def test_coin_state_members():
    assert CoinState.IDLE.name == "IDLE"
    assert CoinState.POSITION_OPEN.name == "POSITION_OPEN"
    assert CoinState.COOLDOWN.name == "COOLDOWN"
