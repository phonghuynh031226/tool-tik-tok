"""Unit tests for Dashboard v3 redesign requirements:
- Toast positioning, auto-repositioning on resize/move, non-empty sanitization with Vietnamese fallbacks
- Video download error handling, retry button, ffmpeg/ffprobe missing instructions
- 3-step stepper indicators
- Channel selection with radio cards
- Ghost Dry-run button
- Custom calendar popup with T2-CN (Monday start) and SchedulePickerWidget live feedback
- Worker error logging to logs/studio.log (Part F)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtGui import QMoveEvent, QResizeEvent
from PySide6.QtWidgets import QApplication

from app.contracts import ChannelAccount, JobStatus
from app.errors import DownloadFailed
from app.ui.components import (
    CustomCalendarPopup, SchedulePickerWidget, ToastManager, ToastNotification, WorkflowStepper,
)
from app.ui.components.toast import DEFAULT_FALLBACK_MESSAGES, DEFAULT_FALLBACK_TITLES
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer
from app.workers.service_workers import (
    DownloadVideoWorker, FetchMetaWorker, GenerateContentWorker, UploadYouTubeWorker, _safe_error,
)


@pytest.fixture
def test_container():
    return ServiceContainer.create_fake()


# -----------------------------------------------------------------------------
# 1. Toast Tests: Pinned bottom-right, Reposition on resize/move, Never empty
# -----------------------------------------------------------------------------
def test_toast_never_empty_and_vietnamese_fallbacks(qtbot):
    """Toast title and message must never be empty or placeholder dashes."""
    for t_type in ("error", "warning", "info", "success"):
        # Test completely empty
        toast_empty = ToastNotification(t_type, "", "")
        qtbot.addWidget(toast_empty)
        assert toast_empty.lbl_title.text() == DEFAULT_FALLBACK_TITLES[t_type]
        assert toast_empty.lbl_msg.text() == DEFAULT_FALLBACK_MESSAGES[t_type]

        # Test placeholder dashes
        toast_dash = ToastNotification(t_type, "—", "—")
        qtbot.addWidget(toast_dash)
        assert toast_dash.lbl_title.text() == DEFAULT_FALLBACK_TITLES[t_type]
        assert toast_dash.lbl_msg.text() == DEFAULT_FALLBACK_MESSAGES[t_type]


def test_toast_manager_repositions_on_window_resize_and_move(qtbot, test_container):
    """ToastManager pins toasts to bottom-right and repositions on resize or move."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()

    tm = window.toast_manager
    toast = tm.info("Thông báo kiểm tra", "Nội dung thông báo")
    qtbot.waitUntil(lambda: toast.isVisible(), timeout=2000)

    # Verify initial position is at bottom-right
    init_x = toast.x()
    init_y = toast.y()
    assert init_x > 800
    assert init_y > 500

    # Resize window to larger size (1600 x 900)
    window.resize(1600, 900)
    QApplication.processEvents()
    assert toast.x() > init_x
    assert toast.y() > init_y

    # Move window
    window.move(window.x() + 50, window.y() + 50)
    QApplication.processEvents()
    # Still inside window rect
    assert toast.x() > 1100
    assert toast.y() > 700


# -----------------------------------------------------------------------------
# 2. Video Download Error: Real Vietnamese cause, Retry button, FFmpeg instructions
# -----------------------------------------------------------------------------
def test_video_download_error_display_and_retry(qtbot, test_container):
    """Download error shows user_message, status Thất bại, and Retry button works."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    page.edit_url.setText("https://www.tiktok.com/@user/video/123456789")

    # Simulate download failure
    error_msg = "Không thể tải video TikTok do liên kết đã bị xóa hoặc tài khoản đặt chế độ riêng tư."
    page._on_download_error(error_msg)

    assert not page.download_error_box.isHidden()
    assert error_msg in page.lbl_error_reason.text()
    assert page.lbl_meta_status.text() == "Trạng thái: Thất bại"
    assert not page.btn_retry_download.isHidden()

    # Click retry button
    with patch.object(page, "_on_download_clicked") as mock_retry:
        page.btn_retry_download.click()
        mock_retry.assert_called_once()


def test_missing_ffmpeg_explicit_instructions():
    """Missing ffmpeg/ffprobe must explicitly guide placing binaries in bin/ folder."""
    err = DownloadFailed("Không tìm thấy ffmpeg trên hệ thống.")
    safe_msg = _safe_error(err, "Lỗi mặc định", event="download_video_failed")
    assert "ffmpeg.exe" in safe_msg
    assert "ffprobe.exe" in safe_msg
    assert "thư mục bin" in safe_msg


# -----------------------------------------------------------------------------
# 3. Stepper 3 Steps Structure
# -----------------------------------------------------------------------------
def test_stepper_3_steps_structure(qtbot, test_container):
    """WorkflowStepper must have 3 steps: Video, Nội dung AI, Đăng YouTube."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    stepper = window.page_dashboard.stepper

    assert isinstance(stepper, WorkflowStepper)
    assert len(stepper._items) == 3
    assert stepper._items[1].lbl_title.text() == "Video"
    assert stepper._items[2].lbl_title.text() == "Nội dung AI"
    assert stepper._items[3].lbl_title.text() == "Đăng YouTube"


# -----------------------------------------------------------------------------
# 4. YouTube Channel Selection Radio Cards
# -----------------------------------------------------------------------------
def test_channel_radio_cards_selection_and_expired(qtbot, test_container):
    """Visual radio cards for accounts, with default pre-selected and expired dimming."""
    acc_def = ChannelAccount("ch-1", "Kênh Chính", is_default=True, status="connected")
    acc_exp = ChannelAccount("ch-2", "Kênh Phụ", is_default=False, status="expired")

    test_container.youtube.list_accounts = MagicMock(return_value=[acc_def, acc_exp])
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    qtbot.waitUntil(lambda: len(page._channel_cards) == 2, timeout=5000)
    card1 = page._channel_cards[0]
    card2 = page._channel_cards[1]

    # Default is selected
    assert card1._is_selected is True
    assert card2._is_selected is False
    assert page.state.channel_id == "ch-1"

    # Expired card has reauth button
    assert card2.btn_reauth is not None
    assert getattr(card1, "btn_reauth", None) is None


# -----------------------------------------------------------------------------
# 5. Ghost Dry-Run Button
# -----------------------------------------------------------------------------
def test_ghost_dry_run_button_locked_and_execution(qtbot, test_container, tmp_path):
    """btn_dry_run is locked until safety gates pass, and triggers dry-run workflow."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    # Initially locked
    assert not page.btn_dry_run.isEnabled()
    assert not page.btn_upload.isEnabled()

    fake_video = tmp_path / "vid.mp4"
    fake_video.write_bytes(b"data")
    window.job_state.set_local_file(fake_video)
    page.edit_title.setText("Tiêu đề hợp lệ")
    assert not page.btn_dry_run.isEnabled()

    page.radio_kids_no.click()
    assert not page.btn_dry_run.isEnabled()

    page.chk_rights.click()
    assert page.btn_dry_run.isEnabled()

    # Triggering dry run opens confirmation and sets dry_run=True
    with patch("app.ui.pages.dashboard.UploadConfirmDialog") as mock_dlg_cls:
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = mock_dlg.DialogCode.Accepted
        mock_dlg_cls.return_value = mock_dlg

        page.btn_dry_run.click()
        assert window.job_state.dry_run is True


# -----------------------------------------------------------------------------
# 6. Custom Calendar Popup & SchedulePickerWidget
# -----------------------------------------------------------------------------
def test_custom_calendar_popup_weekdays_and_navigation(qtbot):
    """Calendar popup has T2-CN (Monday start), navigates months, and disables past dates."""
    popup = CustomCalendarPopup(QDate.currentDate())
    qtbot.addWidget(popup)

    day_labels = [popup.week_header_layout.itemAt(i).widget().text() for i in range(7)]
    assert day_labels == ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    # Month navigation
    init_month_text = popup.lbl_month_year.text()
    popup.btn_next.click()
    assert popup.lbl_month_year.text() != init_month_text
    popup.btn_prev.click()
    assert popup.lbl_month_year.text() == init_month_text


def test_schedule_picker_quick_chips_and_validation(qtbot):
    """Quick chips update time, and live summary displays countdown or red error for < 10 min."""
    picker = SchedulePickerWidget()
    qtbot.addWidget(picker)

    # Click +1 giờ
    picker.btn_chip_plus_1h.click()
    assert picker.is_valid()
    assert "Sẽ công khai lúc" in picker.lbl_summary.text()
    assert "còn" in picker.lbl_summary.text()

    # Manually set to past / less than 10 minutes to trigger validation error
    past_dt = datetime.now() + timedelta(minutes=3)
    picker.set_datetime(past_dt)
    assert not picker.is_valid()
    assert "ít nhất 10 phút" in picker.lbl_summary.text()


# -----------------------------------------------------------------------------
# 7. Worker Error Logging (Section F)
# -----------------------------------------------------------------------------
def test_worker_error_logging_format(caplog):
    """Worker error must log event, exc_type, user_message."""
    from app.errors import NetworkError
    import logging

    with caplog.at_level(logging.ERROR):
        msg = _safe_error(
            NetworkError("Connection timed out"),
            "Không thể kết nối",
            event="fetch_metadata_failed",
        )
        assert "Không thể kết nối" in msg
        log_record = next((r for r in caplog.records if r.levelname == "ERROR"), None)
        assert log_record is not None
        assert "event=fetch_metadata_failed" in log_record.message
        assert "exc_type=NetworkError" in log_record.message
