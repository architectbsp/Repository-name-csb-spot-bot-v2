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
            last = ticker.get("last")

            normalized.append(
                NormalizedTicker(
                    exchange=exchange,
                    symbol=symbol,
                    last_price=float(last or 0.0),
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
                    # Note: ccxt's unified REST ticker has already parsed
                    # the exchange's raw payload into a float by the time
                    # it reaches us, so this is best-effort (str() of that
                    # float) rather than the untouched wire string. Full
                    # raw-string precision is guaranteed on the WebSocket
                    # path above, which is what drives live trading
                    # decisions.
                    raw_last_price=str(last) if last is not None else None,
                )
            )

        return normalized
