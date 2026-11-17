"""Desktop entry point using the production service container."""

import sys

# Set Windows AppUserModelID so taskbar groups under Clivo and displays official brand icon
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clivo.App")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication, QMainWindow

try:
    from app.security.logging import configure_logging
except ImportError:
    try:
        from pathlib import Path
        main_repo = Path(__file__).resolve().parent.parent / "tool-tik-tok"
        if main_repo.exists() and str(main_repo) not in sys.path:
            sys.path.append(str(main_repo))
        from app.security.logging import configure_logging
    except Exception:
        configure_logging = None


def create_window() -> QMainWindow:
    from app.ui.main_window import MainWindow
    window = MainWindow()
    return window


def main() -> int:
    if configure_logging is not None:
        configure_logging(include_app=True)
    application = QApplication(sys.argv)
    from app.ui.branding import APP_NAME, get_app_icon
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
