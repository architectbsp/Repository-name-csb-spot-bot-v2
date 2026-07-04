from app.core.market_scanner import MarketScanner


class BotEngine:
    def __init__(self):
        self.running = False
        self.market_scanner = MarketScanner()

    def start(self):
        self.running = True
        print("Bot started")

    def stop(self):
        self.running = False
        print("Bot stopped")
