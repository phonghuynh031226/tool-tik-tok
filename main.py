"""Desktop entry point using the production service container."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow


def create_window() -> QMainWindow:
    from app.ui.main_window import MainWindow
    window = MainWindow()
    return window


def main() -> int:
    application = QApplication(sys.argv)
    window = create_window()
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
