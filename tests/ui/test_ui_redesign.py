"""Tests for UI redesign: design tokens, responsive layouts, icons, components, and toast notifications."""

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QResizeEvent
from PySide6.QtWidgets import QApplication, QLabel

from app.contracts import JobStatus
from app.ui import icons, tokens
from app.ui.components import (
    AppButton, Card, ConfirmDialog, EmptyState, LabeledInput, StatCard,
    StatusBadge, ToastManager, ToastNotification,
)
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def test_design_tokens_validity():
    """Verify design tokens have valid positive font sizes and spacing."""
    assert tokens.FONT_SIZE_XS > 0
    assert tokens.FONT_SIZE_SM > 0
    assert tokens.FONT_SIZE_BASE > 0
    assert tokens.FONT_SIZE_MD > 0
    assert tokens.FONT_SIZE_LG > 0
    assert tokens.FONT_SIZE_XL > 0
    assert tokens.FONT_SIZE_2XL > 0
    assert tokens.FONT_SIZE_3XL > 0

    assert tokens.SPACE_XS % 4 == 0 or tokens.SPACE_XS % 2 == 0
    assert tokens.SPACE_SM % 4 == 0
    assert tokens.SPACE_MD % 4 == 0
    assert tokens.SPACE_LG % 4 == 0
    assert tokens.SPACE_XL % 4 == 0

    assert tokens.SIDEBAR_COLLAPSE_THRESHOLD == 1100
    assert tokens.WINDOW_MIN_WIDTH >= 1000
    assert tokens.WINDOW_MIN_HEIGHT >= 640


def test_qtawesome_icon_manager(qtbot):
    """Verify semantic icon resolution and valid QIcons."""
    for semantic_name in ("dashboard", "video", "creation", "youtube", "history", "cog", "download", "upload", "refresh"):
        ico = icons.get_icon(semantic_name)
        assert isinstance(ico, QIcon)
        assert not ico.isNull()

    state_ico = icons.get_state_icon("download", color="#ffffff", color_hover="#38bdf8")
    assert isinstance(state_ico, QIcon)
    assert not state_ico.isNull()


def test_app_buttons(qtbot):
    """Test AppButton variants and icon updates."""
    btn_p = AppButton("Lưu", variant="primary", icon_name="content-save")
    qtbot.addWidget(btn_p)
    assert btn_p.property("class") == "btnPrimary"
    assert not btn_p.icon().isNull()

    btn_d = AppButton("Xóa", variant="danger", icon_name="trash-can")
    qtbot.addWidget(btn_d)
    assert btn_d.property("class") == "btnDanger"

    btn_g = AppButton("Đóng", variant="ghost")
    qtbot.addWidget(btn_g)
    assert btn_g.property("class") == "btnGhost"

    # Test changing icon name dynamically
    btn_p.set_icon_name("refresh")
    assert not btn_p.icon().isNull()


def test_status_badge(qtbot):
    """Test StatusBadge rendering for various JobStatus."""
    badge_done = StatusBadge(JobStatus.UPLOADED)
    qtbot.addWidget(badge_done)
    assert badge_done.text() == "Đã xuất bản"

    badge_failed = StatusBadge(JobStatus.FAILED)
    qtbot.addWidget(badge_failed)
    assert badge_failed.text() == "Thất bại"

    badge_dry = StatusBadge("DRY_RUN")
    qtbot.addWidget(badge_dry)
    assert badge_dry.text() == "Chạy thử"


def test_stat_card(qtbot):
    """Test StatCard component."""
    card = StatCard(label="Tổng số video", value="42", icon_name="video")
    qtbot.addWidget(card)
    assert card.lbl_value.text() == "42"
    assert card.lbl_label.text() == "Tổng số video"

    card.set_value("100")
    assert card.lbl_value.text() == "100"


def test_empty_state(qtbot):
    """Test EmptyState component."""
    called = []
    btn = AppButton("Tải ngay", variant="primary")
    btn.clicked.connect(lambda: called.append(True))
    empty = EmptyState(
        icon_name="info",
        title="Chưa có video nào",
        description="Hãy bắt đầu tải video từ TikTok",
        action_button=btn,
    )
    qtbot.addWidget(empty)
    assert empty.findChildren(QLabel)[1].text() == "Chưa có video nào"
    btn.click()
    assert called == [True]


def test_labeled_input(qtbot):
    """Test LabeledInput component."""
    field = LabeledInput("Tiêu đề", placeholder="Nhập tiêu đề...", hint="Tối đa 100 ký tự")
    qtbot.addWidget(field)
    field.setText("Video ngắn")
    assert field.text == "Video ngắn"


def test_confirm_dialog(qtbot):
    """Test generic ConfirmDialog."""
    dlg = ConfirmDialog(
        title="Xác nhận thao tác",
        message="Bạn có chắc chắn muốn thực hiện hành động này?",
        confirm_text="Đồng ý",
        cancel_text="Hủy",
        is_danger=True,
    )
    qtbot.addWidget(dlg)

    accepted = []
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.btn_confirm.click()
    assert accepted == [True]


def test_sidebar_responsive_collapse_and_expansion(qtbot):
    """Test that sidebar auto-collapses below 1100px and expands at or above 1100px."""
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.show()

    # Wide screen (1280px >= 1100px) -> Sidebar expanded
    window.resize(1280, 720)
    QApplication.processEvents()
    assert not window._sidebar_collapsed
    assert window.sidebar.width() == tokens.SIDEBAR_WIDTH_EXPANDED
    assert window.lbl_footer_title.isVisible()

    # Narrow screen (1000px < 1100px) -> Sidebar collapsed
    window.resize(1000, 640)
    QApplication.processEvents()
    assert window._sidebar_collapsed
    assert window.sidebar.width() == tokens.SIDEBAR_WIDTH_COLLAPSED
    assert not window.lbl_footer_title.isVisible()

    # Expand again
    window.resize(1366, 768)
    QApplication.processEvents()
    assert not window._sidebar_collapsed
    assert window.sidebar.width() == tokens.SIDEBAR_WIDTH_EXPANDED


def test_dashboard_responsive_grid_reflow(qtbot):
    """Test that Dashboard reflows 2 columns when wide (>=1150px) and 1 column when narrow (<1150px)."""
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.show()

    dashboard = window.page_dashboard

    # Wide width
    dashboard._update_layout_mode(1200)
    assert dashboard._is_wide_layout is True
    # Step 1 should be at (0, 0) and Step 3 at (0, 1)
    grid = dashboard.steps_grid
    assert grid.indexOf(dashboard.step1_card) >= 0
    assert grid.indexOf(dashboard.step3_card) >= 0
    # Check column stretch
    assert grid.columnStretch(0) == 1
    assert grid.columnStretch(1) == 1

    # Narrow width
    dashboard._update_layout_mode(1000)
    assert dashboard._is_wide_layout is False
    assert grid.columnStretch(1) == 0


def test_toast_manager_and_notifications(qtbot):
    """Test floating toast manager: creation, display, stack, and close button."""
    container = ServiceContainer.create_fake()
    window = MainWindow(services=container)
    qtbot.addWidget(window)
    window.resize(1200, 700)
    window.show()

    tm = window.toast_manager
    assert len(tm.toasts) == 0

    # Trigger different types of toasts
    window.notify("info", "Thông tin", "Tin nhắn thông báo thường")
    assert len(tm.toasts) == 1

    window.notify("success", "Thành công", "Tác vụ hoàn thành xuất sắc")
    assert len(tm.toasts) == 2

    window.notify("warning", "Cảnh báo", "Vui lòng chú ý")
    assert len(tm.toasts) == 3

    window.notify("error", "Lỗi", "Đã xảy ra sự cố")
    assert len(tm.toasts) == 4

    # Close the newest toast via close button
    toast_top = tm.toasts[-1]
    toast_top.btn_close.click()
    assert len(tm.toasts) == 3
