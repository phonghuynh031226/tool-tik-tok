"""Step 0: open an empty desktop window. No service is connected automatically."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow


def create_window() -> QMainWindow:
    window = QMainWindow()
    window.setWindowTitle('TikTok YouTube Studio')
    window.resize(1000, 700)
    return window


def main() -> int:
    application = QApplication(sys.argv)
    window = create_window()
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
