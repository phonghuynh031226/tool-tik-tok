"""Step 0: open an empty desktop window. No service is connected automatically."""

import sys

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
    window = QMainWindow()
    window.setWindowTitle('TikTok YouTube Studio')
    window.resize(1000, 700)
    return window


def main() -> int:
    if configure_logging is not None:
        configure_logging()
    application = QApplication(sys.argv)
    window = create_window()
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
