from app.core.exchange.models import ExchangeType
from app.core.market_data.models import NormalizedTicker


class MarketDataService:
    def normalize_tickers(
        self,
        exchange: ExchangeType,
        tickers: dict,
    ) -> list[NormalizedTicker]:
        normalized: list[NormalizedTicker] = []

        for symbol, ticker in tickers.items():
            normalized.append(
                NormalizedTicker(
                    exchange=exchange,
                    symbol=symbol,
                    last_price=float(ticker.get("last") or 0.0),
                    volume_24h=float(
                        ticker.get("quoteVolume")
                        or ticker.get("baseVolume")
                        or 0.0
                    ),
                    change_24h=float(
                        ticker.get("percentage") or 0.0
                    ),
                    timestamp=int(
                        ticker.get("timestamp") or 0
                    ),
                )
            )

        return normalized
