class Strategy:
    def should_buy(self, price: float) -> bool:
        return price > 42000

    def should_sell(self, price: float) -> bool:
        return price < 42000
