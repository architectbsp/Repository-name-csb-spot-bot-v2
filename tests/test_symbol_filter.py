from app.core.services.symbol_filter import (
    SymbolFilter,
    is_leveraged_symbol,
)


def test_is_leveraged_symbol_blocks_up_down_3l_3s():
    assert is_leveraged_symbol("BTCUP/USDT")
    assert is_leveraged_symbol("ETHDOWN/USDT")
    assert is_leveraged_symbol("SOL3L/USDT")
    assert is_leveraged_symbol("DOGE3S/USDT")
    assert is_leveraged_symbol("BTCBULL/USDT")
    assert not is_leveraged_symbol("BTC/USDT")
    assert not is_leveraged_symbol("ETH/USDT")


def test_symbol_filter_blacklist_blocks_manual_entries():
    filt = SymbolFilter()
    filt.add("LUNA/USDT")

    assert filt.is_blacklisted("LUNA/USDT")
    assert filt.is_blocked("LUNA/USDT")
    assert filt.is_blocked("BTCUP/USDT")  # regex path
    assert not filt.is_blocked("BTC/USDT")

    assert filt.remove("LUNA/USDT") is True
    assert not filt.is_blacklisted("LUNA/USDT")
