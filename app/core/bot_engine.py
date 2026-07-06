from app.core.market_scanner import MarketScanner
from app.core.watch_list import WatchList
from app.core.position_manager import PositionManager


class BotEngine:
    def __init__(self):
        self.running = False

        self.market_scanner = MarketScanner()
        self.watch_list = WatchList()
        self.position_manager = PositionManager()

    def initialize(self):
        self.market_scanner.initialize()
        self.watch_list.initialize()
        self.position_manager.initialize()

    def shutdown(self):
        self.market_scanner.shutdown()
        self.watch_list.shutdown()
        self.position_manager.shutdown()

    def start(self):
        self.initialize()

        self.market_scanner.start()
        self.watch_list.start()
        self.position_manager.start()

        self.running = True
        print("Bot started")

    def stop(self):
        self.market_scanner.stop()
        self.watch_list.stop()
        self.position_manager.stop()

        self.shutdown()

        self.running = False
        print("Bot stopped")
