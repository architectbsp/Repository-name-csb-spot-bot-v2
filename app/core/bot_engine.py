class BotEngine:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True
        print("Bot started")

    def stop(self):
        self.running = False
        print("Bot stopped")
