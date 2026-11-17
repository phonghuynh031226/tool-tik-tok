"""Capture screenshots of Clivo application in real Windows environment at 1366x768, scale 1.25:
- Dashboard Overview with Sidebar Expanded
- Dashboard Overview with Sidebar Collapsed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parents[2]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Force Windows platform (not offscreen) and 125% DPI scale
if sys.platform == "win32":
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("FORCE_OFFSCREEN", None)
os.environ["QT_SCALE_FACTOR"] = "1.25"
os.environ["STUDIO_USE_FAKES"] = "1"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def capture_clivo_branding_views():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    output_dir = Path("d:/DU AN CA NHAN/tool-tik-tok-ui/.tmp/screenshots_clivo")
    output_dir.mkdir(parents=True, exist_ok=True)

    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    window.show()

    # 1. 1366x768, scale 1.25, Sidebar Expanded
    window.resize(1366, 768)
    window._update_sidebar_state(False)
    app.processEvents()

    # Ensure dashboard page is selected (tab index 0)
    window.btn_nav_dashboard.click()
    app.processEvents()

    pixmap_expanded = window.grab()
    path_expanded = output_dir / "clivo_overview_sidebar_expanded_1366x768_scale125.png"
    pixmap_expanded.save(str(path_expanded))
    print(f"Captured: {path_expanded.name}")

    # 2. 1366x768, scale 1.25, Sidebar Collapsed
    window._update_sidebar_state(True)
    app.processEvents()

    pixmap_collapsed = window.grab()
    path_collapsed = output_dir / "clivo_overview_sidebar_collapsed_1366x768_scale125.png"
    pixmap_collapsed.save(str(path_collapsed))
    print(f"Captured: {path_collapsed.name}")

    window.close()
    print(f"All Clivo branding screenshots captured in: {output_dir}")


if __name__ == "__main__":
    capture_clivo_branding_views()
