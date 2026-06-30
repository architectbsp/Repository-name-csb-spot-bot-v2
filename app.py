import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSB Spot Bot v2")

        label = QLabel("CSB Spot Bot v2 UI")
        label.setStyleSheet("font-size: 18px;")

        self.setCentralWidget(label)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(400, 300)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
