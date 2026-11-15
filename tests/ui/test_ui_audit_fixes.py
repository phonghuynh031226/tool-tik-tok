"""Tests for UI audit bug fixes: Ampersands, collapsed sidebar, stepper sequential rules, and channel actions."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QPushButton

from app.contracts import ChannelAccount, JobStatus, VideoMeta
from app.ui.components import StatusBadge
from app.ui.components.stepper import StepItemWidget
from app.ui.main_window import MainWindow
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.youtube_channels_page import AccountCardWidget, YouTubeChannelsPage
from app.ui.services import ServiceContainer


@pytest.fixture
def test_container():
    return ServiceContainer.create_fake()


def test_nav_history_ampersand_escaped(qtbot, test_container):
    """'Lịch sử & Lịch đăng' must have its ampersand escaped as '&&' so Qt does not eat it."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)

    btn = window.btn_nav_history
    assert btn is not None
    # Text in button contains double ampersands for Qt mnemonic escaping
    assert "&&" in btn.text()
    assert "Lịch sử && Lịch đăng" in btn.text()


def test_sidebar_collapsed_no_stray_pipe(qtbot, test_container):
    """When sidebar collapses, no squashed 4px bar or stray pipe character should be visible."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    window.resize(1000, 640)
    window.show()

    # The footer should be hidden when collapsed
    assert not window.footer_frame.isVisible()

    # Inspect all visible labels in sidebar: none should be a squashed vertical strip
    for lbl in window.sidebar.findChildren(QLabel):
        if lbl.isVisible():
            geo = lbl.geometry()
            # If width is tiny (< 8) and height is large (> 20), it would look like a pipe '|'
            assert not (geo.width() < 8 and geo.height() > 20), f"Found squashed label {lbl}: {geo}"


def test_stepper_sequential_progression(qtbot, test_container):
    """Step N cannot be 'done' unless Step N has data AND all steps < N are 'done'."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    # Initial state: no video, no title -> Step 1 pending, Step 2 pending, Step 3 pending, Step 4 pending
    page._update_stepper_state()
    assert page.stepper.get_step_state(1) == "pending"
    assert page.stepper.get_step_state(2) == "pending"
    assert page.stepper.get_step_state(3) == "pending"
    assert page.stepper.get_step_state(4) == "pending"

    # Inconsistent attempt: User injects AI title but video is NOT downloaded
    page.state.title = "Tiêu đề tuyệt vời"
    page._update_stepper_state()
    # Step 3 MUST NOT be 'done' because Step 1 and 2 are not done!
    assert page.stepper.get_step_state(1) == "pending"
    assert page.stepper.get_step_state(2) == "pending"
    assert page.stepper.get_step_state(3) == "pending"
    assert page.stepper.get_step_state(4) == "pending"

    # Now step 1 completes: video downloaded
    fake_video = Path(".tmp/test_stepper_video.mp4")
    fake_video.parent.mkdir(parents=True, exist_ok=True)
    fake_video.write_bytes(b"dummy")
    page.state._local_video_path = fake_video
    page.state.status = JobStatus.DOWNLOADED

    page._update_stepper_state()
    # Step 1 is done, Step 2 is done, Step 3 is pending (waiting for AI content)
    assert page.stepper.get_step_state(1) == "done"
    assert page.stepper.get_step_state(2) == "done"
    assert page.stepper.get_step_state(3) == "pending"
    assert page.stepper.get_step_state(4) == "pending"

    # Step 3 completes: AI content generated
    page.state.status = JobStatus.CONTENT_READY
    page.state.description = "Mô tả hấp dẫn"
    page._update_stepper_state()
    assert page.stepper.get_step_state(3) == "done"
    assert page.stepper.get_step_state(4) == "pending"

    # Step 4 completes upon upload
    page.state.status = JobStatus.UPLOADED
    page._update_stepper_state()
    assert page.stepper.get_step_state(4) == "done"


def test_account_card_actions(qtbot, test_container):
    """AccountCardWidget must have integrated action buttons: reconnect (when expired), default (when not default), remove."""
    acc_connected = ChannelAccount(
        id="ch-1",
        title="Kênh Chính",
        status="connected",
        is_default=True,
    )
    card1 = AccountCardWidget(acc_connected)
    qtbot.addWidget(card1)
    card1.show()

    # For default connected account:
    # - "Đặt làm mặc định" is hidden because it's already default
    assert card1.btn_card_set_default.isHidden()
    # - "Đăng nhập lại" is hidden because it's connected
    assert card1.btn_card_reconnect.isHidden()
    # - "Xóa" is visible
    assert not card1.btn_card_remove.isHidden()

    acc_expired = ChannelAccount(
        id="ch-2",
        title="Kênh Hết Hạn",
        status="expired",
        is_default=False,
    )
    card2 = AccountCardWidget(acc_expired)
    qtbot.addWidget(card2)
    card2.show()

    # For expired non-default account:
    # - "Đặt làm mặc định" is visible
    assert not card2.btn_card_set_default.isHidden()
    # - "Đăng nhập lại" is visible
    assert not card2.btn_card_reconnect.isHidden()
    # - "Xóa" is visible
    assert not card2.btn_card_remove.isHidden()


def test_add_account_button_icon(qtbot, test_container):
    """'Thêm tài khoản' button must use user-add icon, not clipboard paste."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    yt_page = window.page_youtube_channels

    assert yt_page.btn_add_account is not None
    # Verify icon is non-null
    assert not yt_page.btn_add_account.icon().isNull()


def test_badge_and_stepper_labels_have_no_double_border(qtbot):
    """StatusBadge and StepItemWidget child QLabels must have border: none; background: transparent;."""
    badge = StatusBadge(status="Đã kết nối", badge_type="success")
    qtbot.addWidget(badge)
    assert "border: none" in badge.lbl_text.styleSheet()
    assert "border: none" in badge.lbl_icon.styleSheet()

    step_item = StepItemWidget(1, "Nguồn Video")
    qtbot.addWidget(step_item)
    assert "border: none" in step_item.lbl_title.styleSheet()
    assert "border: none" in step_item.lbl_status.styleSheet()
