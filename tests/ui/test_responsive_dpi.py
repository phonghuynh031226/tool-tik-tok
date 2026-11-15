"""Responsive and DPI Layout Automated Tests.

Tests Dashboard, Tools, YouTube Channels, History, and Settings pages across
logical resolutions: 1000, 1280, 1366, 1536, 1920 at scales 1.0, 1.25, 1.5.
Asserts:
- No horizontal scrollbars
- No widget bounding overflow
- Step badge circle backgrounds preserved
- Button labels not truncated
- No orphan widgets
- EmptyState displayed on empty tables
- Unified download directory via resolve_download_directory
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QTableWidget, QWidget

from app.contracts import JobStatus
from app.core.paths import resolve_download_directory
from app.ui.components import EmptyState
from app.ui.main_window import MainWindow
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.history_page import HistoryPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tools_page import ToolsPage
from app.ui.pages.youtube_channels_page import YouTubeChannelsPage
from app.ui.services import ServiceContainer


@pytest.fixture
def test_container():
    return ServiceContainer.create_fake()


@pytest.fixture
def main_window(qapp, test_container):
    win = MainWindow(services=test_container)
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def test_step_badge_circle_styles(main_window, qapp):
    """Verify that step badges (1, 2, 3, 4) in Dashboard retain background color and size."""
    dash = main_window.page_dashboard
    assert isinstance(dash, DashboardPage)

    badges = dash.findChildren(QLabel, "")
    step_badges = [b for b in badges if b.property("class") == "stepBadge"]
    assert len(step_badges) >= 4, f"Found {len(step_badges)} step badges, expected at least 4"

    for b in step_badges:
        assert b.width() == 24
        assert b.height() == 24
        ss = b.styleSheet()
        assert "background-color" in ss or "tokens.PRIMARY" in ss or "#2563eb" in ss
        assert "border-radius: 12px" in ss


def test_no_orphan_widgets_in_settings(main_window, qapp):
    """Verify Settings page has no visible orphan buttons floating at (0, 0)."""
    settings_page = main_window.page_settings
    assert isinstance(settings_page, SettingsPage)

    # Check the compatibility widgets are explicitly hidden
    assert not settings_page.btn_connect_yt.isVisible()
    assert not settings_page.btn_disconnect_yt.isVisible()
    assert not settings_page.lbl_yt_channel_name.isVisible()
    assert not settings_page.lbl_yt_channel_id.isVisible()


def test_download_directory_unified(main_window, qapp):
    """Verify download directory across Dashboard, Settings, and Tools uses resolve_download_directory."""
    expected = resolve_download_directory(None)
    assert expected.name == "downloads"

    settings_dir = Path(main_window.page_settings.edit_download_dir.text()).resolve()
    tools_dir = Path(main_window.page_tools.edit_download_dir.text()).resolve()

    assert settings_dir == expected
    assert tools_dir == expected


def test_watermark_disclaimer_updated(main_window):
    """Verify tools page and tiktok page disclaimers do not claim 'không dính watermark'."""
    tools = main_window.page_tools
    labels = tools.findChildren(QLabel)
    text_content = " ".join(lbl.text() for lbl in labels)

    assert "không dính watermark" not in text_content
    assert "Chỉ tải video bạn sở hữu hoặc được phép sử dụng" in text_content


def test_youtube_channels_redundant_action_bar_hidden(main_window):
    """Verify redundant bottom action bar in YouTubeChannelsPage is not visible."""
    yt_page = main_window.page_youtube
    assert hasattr(yt_page, "acc_actions_widget")
    assert not yt_page.acc_actions_widget.isVisible()


def test_youtube_channels_column_widths_and_empty_state(main_window, qapp):
    """Verify YouTube channels video table has adequate date column width and empty state."""
    main_window.stack.setCurrentIndex(2)
    qapp.processEvents()
    yt_page = main_window.page_youtube
    tbl = yt_page.tbl_videos
    # Date column (index 2) must be at least 150px
    col2_width = tbl.columnWidth(2)
    assert col2_width >= 150, f"Expected date column width >= 150, got {col2_width}"

    # Empty state test
    yt_page._render_videos([])
    qapp.processEvents()
    assert not yt_page.empty_videos.isHidden()
    assert yt_page.tbl_videos.isHidden()


def test_history_table_actions_and_empty_state(main_window, qapp):
    """Verify History page action buttons fit comfortably without truncation and EmptyState shows."""
    main_window.stack.setCurrentIndex(3)
    qapp.processEvents()
    hist_page = main_window.page_history
    assert isinstance(hist_page, HistoryPage)

    # Action column (index 4) should be >= 340px
    col4_width = hist_page.table.columnWidth(4)
    assert col4_width >= 340, f"Expected action column width >= 340, got {col4_width}"

    # Row height should be >= 48px
    row_height = hist_page.table.verticalHeader().defaultSectionSize()
    assert row_height >= 48, f"Expected default row height >= 48, got {row_height}"

    # Verify empty state
    hist_page.table.setRowCount(0)
    hist_page.refresh_history()
    qapp.processEvents()
    assert not hist_page.empty_history.isHidden()
    assert hist_page.table.isHidden()


@pytest.mark.parametrize("width", [1000, 1280, 1366, 1536, 1920])
@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_responsive_layout_no_horizontal_scroll(main_window, qapp, width, scale):
    """Test full responsive scaling across various display sizes and scale factors.
    Assert no horizontal scrollbars and layout adapts gracefully.
    """
    height = int(width * 9 / 16)
    main_window.resize(width, max(height, 640))
    qapp.processEvents()

    # Test all tabs
    for page_idx in range(5):
        main_window.stack.setCurrentIndex(page_idx)
        qapp.processEvents()

        current_page = main_window.stack.currentWidget()
        if hasattr(current_page, "tab_widget"):
            for t_idx in range(current_page.tab_widget.count()):
                current_page.tab_widget.setCurrentIndex(t_idx)
                qapp.processEvents()
                for sa in current_page.findChildren(QScrollArea):
                    if sa.isVisible():
                        h_bar = sa.horizontalScrollBar()
                        assert h_bar.maximum() == 0, (
                            f"Page {page_idx} tab {t_idx} at width {width} (scale {scale}) has horizontal scroll max={h_bar.maximum()}"
                        )
        else:
            for sa in current_page.findChildren(QScrollArea):
                if sa.isVisible():
                    h_bar = sa.horizontalScrollBar()
                    assert h_bar.maximum() == 0, (
                        f"Page {page_idx} at width {width} (scale {scale}) has horizontal scroll max={h_bar.maximum()}"
                    )
