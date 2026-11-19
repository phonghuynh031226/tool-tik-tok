"""Desktop entry point using the production service container."""

import sys
from typing import TYPE_CHECKING

from app.security.logging import configure_logging, enable_crash_logging

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow


def create_window() -> 'QMainWindow':
    from app.ui.main_window import MainWindow
    window = MainWindow()
    return window


def main() -> int:
    enable_crash_logging()
    configure_logging(include_app=True)
    from PySide6.QtWidgets import QApplication

    application = QApplication(sys.argv)
    window = create_window()
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
