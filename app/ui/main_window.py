from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton

from app.core.bot_engine import BotEngine
from app.core.market_data import MarketData


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.engine = BotEngine()
        self.data = MarketData()

        self.setWindowTitle("CSB Spot Bot v2")

        central = QWidget()
        layout = QVBoxLayout()

        self.status_label = QLabel("Status: Stopped")
        self.price_label = QLabel("BTC: 0.0")

        start_btn = QPushButton("Start Bot")
        stop_btn = QPushButton("Stop Bot")
        refresh_btn = QPushButton("Refresh Price")

        start_btn.clicked.connect(self.start_bot)
        stop_btn.clicked.connect(self.stop_bot)
        refresh_btn.clicked.connect(self.refresh_price)

        layout.addWidget(self.status_label)
        layout.addWidget(self.price_label)
        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(refresh_btn)

        central.setLayout(layout)
        self.setCentralWidget(central)

    def start_bot(self):
        self.engine.start()
        self.status_label.setText("Status: Running")

    def stop_bot(self):
        self.engine.stop()
        self.status_label.setText("Status: Stopped")

    def refresh_price(self):
        data = self.data.get_price("BTCUSDT")
        self.price_label.setText(f"BTC: {data['price']}")
