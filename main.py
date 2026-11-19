"""Clivo startup: native crash capture precedes environment isolation and Qt."""
import sys
from typing import TYPE_CHECKING
from app.security.logging import configure_logging, enable_crash_logging

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow


def create_window() -> 'QMainWindow':
    # MainWindow applies UiPreferences (saved language/theme) after UI creation.
    from app.ui.main_window import MainWindow
    return MainWindow()


def main() -> int:
    enable_crash_logging()
    from app.core.runtime_env import configure_native_environment
    configure_native_environment()
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Clivo.App')
    # configure_logging imports QtCore to record the Qt version; isolation is ready.
    configure_logging(include_app=True)
    from PySide6.QtWidgets import QApplication
    from app.ui.branding import APP_NAME, get_app_icon
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    icon = get_app_icon()
    if not icon.isNull():
        application.setWindowIcon(icon)
    window = create_window()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
