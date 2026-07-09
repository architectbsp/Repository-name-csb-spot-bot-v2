from app.core.exchange.binance import BinanceExchange
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.core.config.settings import ExchangeSettings


def test_exchange_manager_creation():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        BinanceExchange(
            ExchangeState(
                exchange=ExchangeType.BINANCE,
                enabled=True,
            ),
            ExchangeSettings(),
        ),
    )

    manager = ExchangeManager(registry)

    assert manager.enabled()


def test_exchange_manager_price_stream():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        BinanceExchange(
            ExchangeState(
                exchange=ExchangeType.BINANCE,
                enabled=True,
            ),
            ExchangeSettings(),
        ),
    )

    manager = ExchangeManager(registry)

    assert manager.get_price_stream(
        ExchangeType.BINANCE,
    ) is not None
