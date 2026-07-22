"""
docs/BUSINESS_RULES.md §9 "Order Submission Armor": LOT_SIZE/stepSize and
PRICE_FILTER/tickSize truncation must only ever be applied at order
submission time, and must always truncate (floor) rather than round --
rounding a quantity up could submit more than the wallet can afford, and
rounding a price up could submit an invalid tick.
"""

import ccxt

from app.core.exchange.base import truncate_to_precision


def _binance_client_with_market(price_precision: float, amount_precision: float):
    client = ccxt.binance()
    client.set_markets(
        {
            "BTC/USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT",
                "base": "BTC",
                "quote": "USDT",
                "precision": {
                    "amount": amount_precision,
                    "price": price_precision,
                },
                "limits": {},
                "active": True,
                "spot": True,
                "type": "spot",
            }
        }
    )
    return client


def test_truncate_to_precision_floors_price_never_rounds_up():
    client = _binance_client_with_market(price_precision=0.01, amount_precision=0.000001)

    # 100.129999 rounds to 100.13 under normal ROUND semantics, but must
    # truncate down to 100.12 to avoid submitting an invalid/aggressive
    # tick.
    assert truncate_to_precision(client, "BTC/USDT", 100.129999, precision_key="price") == 100.12


def test_truncate_to_precision_floors_amount_never_rounds_up():
    client = _binance_client_with_market(price_precision=0.01, amount_precision=0.000001)

    # 0.9999995 rounds to 1.0 under normal ROUND semantics, but must
    # truncate down to 0.999999 so the order never requests more than the
    # wallet can actually afford.
    assert truncate_to_precision(client, "BTC/USDT", 0.9999995, precision_key="amount") == 0.999999


def test_binance_exchange_normalize_price_uses_truncation():
    from app.core.config.settings import ExchangeSettings
    from app.core.exchange.binance import BinanceExchange
    from app.core.exchange.models import ExchangeState, ExchangeType

    exchange = BinanceExchange(
        ExchangeState(exchange=ExchangeType.BINANCE),
        ExchangeSettings(exchange="binance", api_key="", api_secret="", testnet=True),
    )
    exchange.client.set_markets(
        {
            "BTC/USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT",
                "base": "BTC",
                "quote": "USDT",
                "precision": {"amount": 0.000001, "price": 0.01},
                "limits": {},
                "active": True,
                "spot": True,
                "type": "spot",
            }
        }
    )

    assert exchange.normalize_price("BTC/USDT", 100.129999) == 100.12
