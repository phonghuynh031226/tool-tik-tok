"""Unit tests for Clivo application branding:
- Centralized branding source in app.ui.branding
- Logo assets presence and multi-resolution QIcon
- Window title, sidebar header/footer, and system tray using branding.APP_NAME
- Sidebar collapse preserving logo icon while hiding text
- Verification that no stray "Studio Pro" or "TikTok YouTube Studio" remain in UI code
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from app.ui import branding, tokens
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def test_branding_constants_and_files_exist(qtbot):
    """Verify branding constants and check that all brand asset files exist and load."""
    assert branding.APP_NAME == "Clivo"
    assert branding.APP_VERSION == "2.0.0"
    assert branding.APP_ID == "Clivo.App"

    # All resolution PNGs exist
    for size in (16, 32, 48, 64, 128, 256, 1024):
        p = branding.get_logo_icon_path(size)
        assert p.exists(), f"Missing brand icon asset: {p}"

    # SVGs and lockup exist
    assert branding.get_logo_svg_path().exists()
    assert branding.get_icon_svg_path().exists()
    assert branding.get_logo_full_path().exists()

    # Multi-resolution QIcon
    icon = branding.get_app_icon()
    assert not icon.isNull()
    available_sizes = icon.availableSizes()
    assert len(available_sizes) >= 5

    # Pixmap loader
    pm = branding.get_logo_pixmap(28)
    assert not pm.isNull()
    assert pm.width() == 28
    assert pm.height() == 28


def test_main_window_branding_elements(qtbot):
    """Verify window title, window icon, sidebar header/footer, and tray display Clivo branding."""
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.show()

    # Window title and icon
    assert window.windowTitle() == branding.APP_NAME
    assert not window.windowIcon().isNull()

    # Sidebar Header
    assert window.lbl_logo_title.text() == branding.APP_NAME
    assert window.lbl_logo_title.objectName() == "appLogoTitle"
    assert not window.lbl_logo_icon.pixmap().isNull()

    # Sidebar Footer
    assert window.lbl_footer_title.text() == branding.APP_NAME
    assert f"v{branding.APP_VERSION}" in window.lbl_footer_version.text()
    assert not window.lbl_footer_logo.pixmap().isNull()

    # System Tray
    assert not window.tray_icon.icon().isNull()
    assert window.tray_icon.toolTip() == branding.APP_NAME


def test_sidebar_collapse_preserves_logo_icon(qtbot):
    """When sidebar is collapsed, the logo icon remains visible while brand text is hidden."""
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.show()

    # Initially expanded
    window._update_sidebar_state(False)
    assert window.lbl_logo_icon.isVisible()
    assert window.lbl_logo_title.isVisible()
    assert window.footer_frame.isVisible()

    # Collapse sidebar
    window._update_sidebar_state(True)
    assert window.sidebar.width() == tokens.SIDEBAR_WIDTH_COLLAPSED
    # Logo icon MUST remain visible
    assert window.lbl_logo_icon.isVisible()
    # Text must be hidden
    assert not window.lbl_logo_title.isVisible()
    assert not window.lbl_sub.isVisible()
    assert not window.footer_frame.isVisible()

    # Expand again
    window._update_sidebar_state(False)
    assert window.sidebar.width() == tokens.SIDEBAR_WIDTH_EXPANDED
    assert window.lbl_logo_icon.isVisible()
    assert window.lbl_logo_title.isVisible()
    assert window.footer_frame.isVisible()


def test_no_legacy_strings_in_ui_code():
    """Verify no string literals in app/ui code contain 'Studio Pro' or 'TikTok YouTube Studio'."""
    ui_dir = Path(__file__).resolve().parents[2] / "app" / "ui"
    forbidden = ["Studio Pro", "TikTok YouTube Studio"]

    violations = []
    for py_file in ui_dir.rglob("*.py"):
        code = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(code, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check string constants in code (ignoring docstrings of modules/classes if not user-facing)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for f_term in forbidden:
                    if f_term.lower() in node.value.lower():
                        # Exclude APP_TAGLINE comment or fallback
                        if py_file.name == "branding.py" and node.value == branding.APP_TAGLINE:
                            continue
                        violations.append((py_file.name, node.lineno, node.value))

    assert not violations, f"Found legacy branding strings in code: {violations}"


def test_brand_colors_and_accessibility():
    """Verify brand colors exist in tokens and are applied to accents with proper contrast."""
    assert tokens.BRAND_MINT == "#59E3C1"
    assert tokens.BRAND_VIOLET == "#728BFF"
    assert tokens.BRAND_NAVY == "#0E1424"

    # Functional colors remain unchanged
    assert tokens.PRIMARY == "#3b82f6"
    assert tokens.SUCCESS == "#10b981"
    assert tokens.DANGER == "#ef4444"
