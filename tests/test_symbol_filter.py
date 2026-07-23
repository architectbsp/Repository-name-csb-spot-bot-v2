"""
Sprint 9 -- SymbolFilter / BlacklistManager unit tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.config.config_manager import ConfigUpdatedEvent
from app.core.exchange.models import ExchangeType
from app.core.market_scanner import MarketScanner
from app.core.risk_manager import RiskManager
from app.core.services.symbol_filter import (
    BlacklistManager,
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
    assert filt.is_blocked("BTCUP/USDT")  # regex / leverage path
    assert not filt.is_blocked("BTC/USDT")

    assert filt.remove("LUNA/USDT") is True
    assert not filt.is_blacklisted("LUNA/USDT")


def test_blacklist_manager_alias_is_symbol_filter():
    assert BlacklistManager is SymbolFilter


def test_filtered_patterns_block_up_down_3l_3s_via_scanner(caplog):
    """Regex kalıbına uyan (UP/DOWN/3L/3S) token'lar Scanner tarafından elenir."""
    scanner = MarketScanner()
    scanner.set_config(
        SimpleNamespace(strategy=SimpleNamespace(min_volume_usd=100))
    )
    filt = SymbolFilter()
    # Drop built-in leverage path by using only Settings patterns on a
    # filter that still has defaults -- BTCUP matches .*UPUSDT$ on compact.
    filt.apply_from_values(
        {
            "blacklist_symbols": "",
            "filtered_patterns": (
                ".*UPUSDT$,.*DOWNUSDT$,.*3LUSDT$,.*3SUSDT$"
            ),
        }
    )
    scanner.set_symbol_filter(filt)

    symbols = [
        SimpleNamespace(symbol="BTC/USDT", volume_24h=150),
        SimpleNamespace(symbol="BTCUP/USDT", volume_24h=150),
        SimpleNamespace(symbol="ETHDOWN/USDT", volume_24h=150),
        SimpleNamespace(symbol="SOL3L/USDT", volume_24h=150),
        SimpleNamespace(symbol="DOGE3S/USDT", volume_24h=150),
    ]

    with caplog.at_level("INFO", logger="app.core.market_scanner"):
        result = scanner.filter_symbols(symbols)

    assert [s.symbol for s in result] == ["BTC/USDT"]
    assert any("BTCUP/USDT" in r.message for r in caplog.records)


def test_settings_blacklist_symbols_blocks_immediately_via_config_updated():
    """Settings üzerinden eklenen coin config.updated ile anında bloklanır."""
    filt = SymbolFilter()
    filt.apply_from_values(
        {"blacklist_symbols": "", "filtered_patterns": ""}
    )
    assert not filt.is_blocked("PEPE/USDT")

    event = ConfigUpdatedEvent(
        changed={"blacklist_symbols": "PEPE/USDT,DOGEUSDT"},
        values={
            "blacklist_symbols": "PEPE/USDT,DOGEUSDT",
            "filtered_patterns": "",
        },
        source="settings_ui",
    )
    filt.on_config_updated(event)

    assert filt.is_blacklisted("PEPE/USDT")
    assert filt.is_blocked("PEPE/USDT")
    assert filt.is_blocked("DOGE/USDT")  # compact DOGEUSDT in CSV
    assert not filt.is_blocked("BTC/USDT")


def test_risk_manager_rejects_buy_for_blacklisted_symbol():
    """Kara listedeki sembol için BUY sinyali gelse bile engellenir."""
    filt = SymbolFilter()
    filt.apply_from_values(
        {"blacklist_symbols": "SCAM/USDT", "filtered_patterns": ""}
    )

    rm = RiskManager()
    rm.set_symbol_filter(filt)
    rm.set_config(
        SimpleNamespace(
            risk=SimpleNamespace(
                max_daily_loss_percent=20.0,
                max_open_positions=10,
                stop_loss_percent=10.0,
                trailing_activation_percent=2.0,
                trailing_percent=2.5,
                max_balance_utilization_percent=99.5,
                max_volume_share_percent=0.1,
                position_sizing_mode=0,
                risk_per_trade_percent=1.0,
                atr_period=14,
                atr_multiplier=2.0,
                volatility_target_percent=0.0,
                volatility_lookback=20,
                kelly_fraction=0.5,
                kelly_min_trades=10,
                dynamic_lookback_trades=0,
                partial_tp_activation_percent=0.0,
                partial_tp_sell_percent=50.0,
            ),
            strategy=SimpleNamespace(
                trading_hours_enabled=0,
                weekend_closed=0,
                quiet_start_hour_utc=2,
                quiet_end_hour_utc=5,
            ),
        )
    )

    exchange = MagicMock()
    exchange.get_quote_balance.return_value = 10_000.0
    rm.set_exchange_manager(exchange)

    positions = MagicMock()
    positions.open_count.return_value = 0
    positions.is_open.return_value = False
    rm.set_position_manager(positions)
    rm.set_order_validator(MagicMock())

    result = rm.open_position(
        exchange_type=ExchangeType.BINANCE,
        symbol="SCAM/USDT",
        price=1.0,
        volume_24h=50_000_000,
    )
    assert result is None
    exchange.execute_trade.assert_not_called()
