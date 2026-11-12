"""Tests for MainWindow and page navigation."""

import pytest
from PySide6.QtWidgets import QStackedWidget

from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def test_main_window_init_and_navigation(qtbot):
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "TikTok YouTube Studio"
    assert window.isVisible()

    stack = window.findChild(QStackedWidget)
    assert stack is not None
    assert stack.count() == 6

    # Test clicking each nav button and verify stack index changes
    window.btn_nav_tiktok.click()
    assert stack.currentIndex() == 1

    window.btn_nav_ai.click()
    assert stack.currentIndex() == 2

    window.btn_nav_youtube.click()
    assert stack.currentIndex() == 3

    window.btn_nav_history.click()
    assert stack.currentIndex() == 4

    window.btn_nav_settings.click()
    assert stack.currentIndex() == 5

    window.btn_nav_dashboard.click()
    assert stack.currentIndex() == 0


def test_shared_state_across_pages(qtbot):
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)

    dashboard = window.page_dashboard
    ai_page = window.page_ai

    # Changing URL in dashboard updates shared state
    dashboard.input_url.setText("https://www.tiktok.com/@test/video/123456")
    assert window.job_state.url == "https://www.tiktok.com/@test/video/123456"

    # Changing title in shared state updates both dashboard and AI page
    window.job_state.title = "Tiêu đề dùng chung"
    assert dashboard.edit_title.text() == "Tiêu đề dùng chung"
    assert ai_page.edit_title.text() == "Tiêu đề dùng chung"
    assert "18/100" in dashboard.lbl_title_counter.text()


def test_dashboard_made_for_kids_not_preselected(qtbot):
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)

    dashboard = window.page_dashboard
    # Neither radio button should be checked initially
    assert not dashboard.radio_kids_yes.isChecked()
    assert not dashboard.radio_kids_no.isChecked()
    assert window.job_state.made_for_kids is None

    # Check that can_upload fails when not selected
    can, reason = window.job_state.can_upload()
    assert not can
    assert "Chưa có file video" in reason

