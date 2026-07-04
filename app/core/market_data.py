import random


class MarketData:
    def __init__(self):
        self._exchange = None

    def get_price(self, symbol: str):
        base = 42000  # fake BTC base price
        fluctuation = random.uniform(-500, 500)

        return {
            "symbol": symbol,
            "price": round(base + fluctuation, 2),
        }
