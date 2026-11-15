"""Test icon mapping and ensure zero missing icons or gray placeholder fallbacks."""

import pytest
from PySide6.QtGui import QIcon

from app.ui import icons


def test_all_icon_map_entries_are_valid(qtbot):
    """Every icon key in ICON_MAP must resolve to a valid non-null QIcon."""
    for key, qta_name in icons.ICON_MAP.items():
        icon = icons.get_icon(key)
        assert isinstance(icon, QIcon), f"Icon '{key}' must return a QIcon"
        assert not icon.isNull(), f"Icon key '{key}' -> '{qta_name}' returned a null QIcon"


def test_specific_remediated_icons(qtbot):
    """Test specific icons that previously caused gray placeholder fallbacks."""
    for name in [
        "paste", "content-paste",
        "folder", "folder-open", "browse",
        "cancel", "close-circle",
        "copy", "content-copy", "content-save",
        "user-add", "account-plus",
        "user-check", "account-check",
        "sync", "refresh",
        "youtube", "history",
    ]:
        icon = icons.get_icon(name)
        assert not icon.isNull(), f"Icon '{name}' should not be null"


def test_missing_icon_warning_logging(qtbot, caplog):
    """Unknown icon names should log a warning and return a fallback placeholder."""
    import logging
    with caplog.at_level(logging.WARNING):
        icon = icons.get_icon("non_existent_crazy_icon_xyz_123")
        assert isinstance(icon, QIcon)
        # Should have logged a warning
        assert any("non_existent_crazy_icon_xyz_123" in record.message for record in caplog.records)
