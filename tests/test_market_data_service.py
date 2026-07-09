from app.core.exchange.models import ExchangeType
from app.core.market_data.service import MarketDataService


def test_normalize_tickers():
    service = MarketDataService()

    tickers = {
        "BTC/USDT": {
            "last": 100000,
            "quoteVolume": 1234567,
            "percentage": 5.5,
            "timestamp": 123456789,
        }
    }

    result = service.normalize_tickers(
        ExchangeType.BINANCE,
        tickers,
    )

    assert len(result) == 1

    ticker = result[0]

    assert ticker.exchange is ExchangeType.BINANCE
    assert ticker.symbol == "BTC/USDT"
    assert ticker.last_price == 100000.0
    assert ticker.volume_24h == 1234567.0
    assert ticker.change_24h == 5.5
    assert ticker.timestamp == 123456789
