from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton

from app.core.bot_engine import BotEngine


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.engine = BotEngine()

        self.setWindowTitle("CSB Spot Bot v2")

        central = QWidget()
        layout = QVBoxLayout()

        self.status_label = QLabel("Status: Stopped")

        start_btn = QPushButton("Start Bot")
        stop_btn = QPushButton("Stop Bot")

        start_btn.clicked.connect(self.start_bot)
        stop_btn.clicked.connect(self.stop_bot)

        layout.addWidget(self.status_label)
        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)

        central.setLayout(layout)
        self.setCentralWidget(central)

    def start_bot(self):
        self.engine.start()
        self.status_label.setText("Status: Running")

    def stop_bot(self):
        self.engine.stop()
        self.status_label.setText("Status: Stopped")
