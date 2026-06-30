from PyQt6.QtWidgets import QMainWindow, QLabel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSB Spot Bot v2")

        label = QLabel("CSB Spot Bot v2 UI (modular)")
        label.setStyleSheet("font-size: 18px;")

        self.setCentralWidget(label)
