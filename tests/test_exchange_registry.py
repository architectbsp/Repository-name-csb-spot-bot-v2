from app.core.exchange.models import (
    ConnectionStatus,
    ExchangeState,
    ExchangeType,
)
from app.core.exchange.registry import ExchangeRegistry


class DummyExchange:
    def __init__(self, exchange_type, enabled=False):
        self.state = ExchangeState(
            exchange=exchange_type,
            status=ConnectionStatus.DISCONNECTED,
            enabled=enabled,
        )


def test_register_and_get():
    registry = ExchangeRegistry()

    exchange = DummyExchange(ExchangeType.BINANCE)

    registry.register(
        ExchangeType.BINANCE,
        exchange,
    )

    assert registry.get(ExchangeType.BINANCE) is exchange


def test_unregister():
    registry = ExchangeRegistry()

    exchange = DummyExchange(ExchangeType.BINANCE)

    registry.register(
        ExchangeType.BINANCE,
        exchange,
    )

    registry.unregister(ExchangeType.BINANCE)

    assert registry.get(ExchangeType.BINANCE) is None


def test_all_returns_copy():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        DummyExchange(ExchangeType.BINANCE),
    )

    data = registry.all()

    data.clear()

    assert len(registry.all()) == 1


def test_enabled_returns_only_enabled():
    registry = ExchangeRegistry()

    registry.register(
        ExchangeType.BINANCE,
        DummyExchange(
            ExchangeType.BINANCE,
            enabled=True,
        ),
    )

    registry.register(
        ExchangeType.BYBIT,
        DummyExchange(
            ExchangeType.BYBIT,
            enabled=False,
        ),
    )

    enabled = registry.enabled()

    assert len(enabled) == 1
    assert enabled[0].state.exchange == ExchangeType.BINANCE
