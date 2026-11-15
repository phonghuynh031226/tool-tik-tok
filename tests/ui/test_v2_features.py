"""Unit tests for redesigned v2 UI components and workflows.

Covers:
1. Stepper indicator in Dashboard (Tổng quan)
2. ToolsPage: standalone TikTok downloader and AI content generator
3. YouTubeChannelsPage: multi-account listing, stats, video table, and channel management
4. HistoryPage: History records and Scheduled uploads tab with local time & countdown
5. SettingsPage: simplified OAuth group
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget

from app.contracts import (
    ChannelAccount, ChannelStats, GeneratedContent, JobStatus,
    UploadRequest, VideoMeta, VideoStats,
)
from app.ui.components import UploadConfirmDialog, WorkflowStepper
from app.ui.main_window import MainWindow
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.history_page import HistoryPage
from app.ui.pages.tools_page import ToolsPage
from app.ui.pages.youtube_channels_page import YouTubeChannelsPage
from app.ui.services import ServiceContainer


@pytest.fixture
def test_container():
    return ServiceContainer.create_fake()


def test_overview_stepper_progression(qtbot, test_container):
    """Test that the 3-step Stepper on Overview page reflects job state properly."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    stepper = page.stepper
    assert isinstance(stepper, WorkflowStepper)

    # Initial: All 3 steps pending
    assert stepper.get_step_state(1) == "pending"
    assert stepper.get_step_state(2) == "pending"
    assert stepper.get_step_state(3) == "pending"

    # Step 1 active when URL entered
    window.job_state.url = "https://www.tiktok.com/@user/video/123"
    page._sync_from_state()
    assert stepper.get_step_state(1) == "active"

    # Step 1 completed when video is ready, Step 2 active
    sample_mp4 = Path(".tmp/sample.mp4")
    window.job_state.local_video_path = sample_mp4
    window.job_state.status = JobStatus.DOWNLOADED
    page._sync_from_state()
    assert stepper.get_step_state(1) == "done"
    assert stepper.get_step_state(2) == "active"

    # Step 2 completed when AI content generated
    window.job_state.title = "Tiêu đề chuẩn SEO mới"
    window.job_state.status = JobStatus.CONTENT_READY
    page._sync_from_state()
    assert stepper.get_step_state(1) == "done"
    assert stepper.get_step_state(2) == "done"

    # Step 3 completed when uploaded
    window.job_state.status = JobStatus.UPLOADED
    page._sync_from_state()
    assert stepper.get_step_state(3) == "done"


def test_tools_page_tiktok_downloader(qtbot, test_container, tmp_path):
    """Test ToolsPage Tab 1: TikTok downloader direct download & folder management."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    tools = window.page_tools

    # Switch to Tools page
    window.btn_nav_tools.click()
    assert window.stack.currentIndex() == 1

    # Enter URL and simulate file pick
    test_file = tmp_path / "offline_video.mp4"
    test_file.write_bytes(b"dummy mp4 binary")

    with patch.object(tools, "_on_pick_file") as mock_pick:
        tools.btn_pick_file.click()
        mock_pick.assert_called_once()

    # Manually append an item to simulate downloaded list
    row = tools.tbl_downloads.rowCount()
    tools.tbl_downloads.insertRow(row)
    tools.tbl_downloads.setItem(row, 0, tools.tbl_downloads.item(row, 0) or QTableWidget().item(0, 0))
    tools._downloaded_files.append({
        "video_id": "vid-direct-101",
        "title": "Direct Downloaded Video",
        "duration": "45s",
        "size": "5.2 MB",
        "path": str(test_file),
        "meta": None,
    })

    # Select and load to main job
    tools.tbl_downloads.selectRow(0)
    tools.btn_load_to_job.click()

    assert window.job_state.local_video_path == test_file
    assert window.job_state.title == "Direct Downloaded Video"


def test_tools_page_ai_standalone(qtbot, test_container):
    """Test ToolsPage Tab 2: Standalone AI content generation without needing a video/channel."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    tools = window.page_tools

    # Switch to tab 2 (Nội dung AI)
    tools.tab_widget.setCurrentIndex(1)

    tools.edit_ai_orig_title.setText("Video hướng dẫn nấu phở bò chuẩn vị")
    tools.edit_ai_orig_desc.setPlainText("Bí quyết nước dùng trong veo và ngọt thanh tự nhiên")

    # Click generate AI
    tools.btn_generate_ai.click()

    # Fake generator should produce content
    qtbot.waitUntil(lambda: bool(tools.edit_title.text()), timeout=5000)

    assert len(tools.edit_title.text()) > 0
    assert len(tools.edit_desc.toPlainText()) > 0
    assert "#" in tools.edit_hashtags.text()

    # Apply to main job
    tools.btn_apply_to_job.click()
    assert window.job_state.title == tools.edit_title.text()
    assert window.job_state.description == tools.edit_desc.toPlainText()


def test_youtube_channels_page(qtbot, test_container):
    """Test YouTubeChannelsPage: Multi-account list, stats display, video table, and account operations."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    yt_page = window.page_youtube_channels

    # Navigate to YouTube Channels
    window.btn_nav_youtube.click()
    assert window.stack.currentIndex() == 2

    # Wait for accounts to load
    qtbot.waitUntil(lambda: len(yt_page._accounts) > 0, timeout=5000)
    assert len(yt_page._accounts) >= 1

    # Verify stats loaded
    qtbot.waitUntil(lambda: yt_page.stat_views.lbl_value.text() != "—", timeout=5000)
    assert yt_page.stat_views.lbl_value.text() != "—"
    assert yt_page.stat_videos.lbl_value.text() != "—"

    # Verify videos loaded
    qtbot.waitUntil(lambda: yt_page.tbl_videos.rowCount() > 0, timeout=5000)
    assert yt_page.tbl_videos.rowCount() > 0

    # Test filtering videos
    first_title = yt_page.tbl_videos.item(0, 1).text()
    yt_page.edit_search.setText(first_title[:4])
    assert yt_page.tbl_videos.rowCount() >= 1

    # Test adding an account
    initial_count = len(yt_page._accounts)
    yt_page.btn_add_account.click()
    qtbot.waitUntil(lambda: len(yt_page._accounts) == initial_count + 1, timeout=5000)
    assert len(yt_page._accounts) == initial_count + 1


def test_history_scheduled_tab(qtbot, test_container):
    """Test HistoryPage Tab 2 (Lịch đăng): Scheduled videos listing, countdown, and sync."""
    # Seed a scheduled record into fake history
    future_time = datetime.now(timezone.utc) + timedelta(hours=2)
    test_container.history.add({
        "video_id": "fake-scheduled-1",
        "title": "Video lên lịch tự động",
        "status": JobStatus.SCHEDULED,
        "publish_at": future_time,
        "channel_title": "Kênh Thử Nghiệm",
        "channel_id": "channel-1",
    })

    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    history_page = window.page_history

    # Switch to History & Schedule
    window.btn_nav_history.click()
    assert window.stack.currentIndex() == 3

    # Switch to Scheduled Tab
    history_page.tab_widget.setCurrentIndex(1)
    history_page.refresh_scheduled()

    assert history_page.tbl_scheduled.rowCount() >= 1

    # Verify Title and Channel
    title_item = history_page.tbl_scheduled.item(0, 1)
    assert title_item.text() == "Video lên lịch tự động"

    # Verify Remaining time countdown contains "Còn"
    countdown_item = history_page.tbl_scheduled.item(0, 4)
    assert "Còn" in countdown_item.text()

    # Test sync scheduled button
    history_page.btn_sync_scheduled.click()
    qtbot.waitUntil(lambda: history_page.btn_sync_scheduled.isEnabled(), timeout=5000)


def test_settings_simplified_oauth(qtbot, test_container):
    """Test SettingsPage has simplified OAuth card pointing to YouTube Channels page."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    settings = window.page_settings

    window.btn_nav_settings.click()
    assert window.stack.currentIndex() == 4

    # Ensure client_secret.json picker exists
    assert settings.edit_client_secret is not None
    assert settings.btn_browse_secret is not None


def test_overview_channel_picker_selection_and_expired(qtbot, test_container):
    """Test destination channel picker populates accounts and handles expired accounts."""
    expired_acc = ChannelAccount("ch-expired", "Kênh Hết Hạn", is_default=False, status="expired")
    valid_acc = ChannelAccount("ch-valid", "Kênh Hợp Lệ", is_default=True, status="connected")

    test_container.youtube.list_accounts = Mock(return_value=[valid_acc, expired_acc])

    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    # Account verification runs in a worker; wait for the UI snapshot.
    qtbot.waitUntil(lambda: page.combo_channel.count() == 2, timeout=5000)
    # Check that combo has both accounts
    assert page.combo_channel.count() == 2
    assert "Kênh Hợp Lệ (Mặc định)" in page.combo_channel.itemText(0)
    assert "Kênh Hết Hạn (Hết hạn)" in page.combo_channel.itemText(1)

    # Default is selected
    assert page.combo_channel.currentIndex() == 0
    assert page.btn_reconnect_channel.isHidden()

    # Selecting expired account reveals reconnect button
    page.combo_channel.setCurrentIndex(1)
    assert not page.btn_reconnect_channel.isHidden()


def test_overview_publish_timing_schedule_mode_and_validation(qtbot, test_container, tmp_path):
    """Test publish timing toggle, QDateTimeEdit initialization, timezone and validation."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    # Default is "Đăng ngay"
    assert page.radio_publish_now.isChecked()
    assert page.schedule_container.isHidden()
    assert page.combo_privacy.isEnabled()

    # Switch to "Hẹn giờ công khai"
    page.radio_publish_schedule.setChecked(True)
    assert not page.schedule_container.isHidden()
    assert not page.combo_privacy.isEnabled()
    assert page.combo_privacy.currentIndex() == 0  # Locked to private
    assert not page.lbl_privacy_hint.isHidden()

    # Timezone label is present
    assert "Múi giờ máy:" in page.lbl_timezone.text()

    # Default datetime is in the future
    dt_now = datetime.now()
    qdt_selected = page.dt_publish.dateTime().toPython()
    assert qdt_selected > dt_now

    # Test Validation: set time in past / less than 10 mins -> invalid
    page.dt_publish.setDateTime(datetime.now() + timedelta(minutes=5))
    valid, err = page._validate_schedule_time()
    assert not valid
    assert "10 phút" in err
    assert not page.lbl_schedule_error.isHidden()

    # Test Validation: set time 2 hours in future -> valid
    page.dt_publish.setDateTime(datetime.now() + timedelta(hours=2))
    valid, err = page._validate_schedule_time()
    assert valid
    assert page.lbl_schedule_error.isHidden()

    # Switch back to "Đăng ngay" -> schedule container hidden, privacy unlocked
    page.radio_publish_now.setChecked(True)
    assert page.schedule_container.isHidden()
    assert page.combo_privacy.isEnabled()


def test_overview_upload_confirm_dialog_modes(qtbot, tmp_path):
    """Test UploadConfirmDialog displays correct info in immediate and scheduled modes."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"dummy")

    # Immediate mode dialog
    req_now = UploadRequest(
        path=video,
        title="Video Test Đăng Ngay",
        description="Mô tả",
        tags=["test"],
        privacy="public",
        made_for_kids=False,
        rights_confirmed=True,
    )
    dlg_now = UploadConfirmDialog(req_now, "Kênh Chính", "UC123")
    qtbot.addWidget(dlg_now)
    assert not dlg_now.lbl_privacy_warning.isHidden()
    assert "PUBLIC" in dlg_now.lbl_privacy_warning.text()

    # Scheduled mode dialog
    future_time = datetime.now(timezone.utc) + timedelta(days=2)
    req_sched = UploadRequest(
        path=video,
        title="Video Test Hẹn Giờ",
        description="Mô tả",
        tags=["test"],
        privacy="private",
        made_for_kids=False,
        rights_confirmed=True,
        publish_at=future_time,
    )
    dlg_sched = UploadConfirmDialog(req_sched, "Kênh Chính", "UC123")
    qtbot.addWidget(dlg_sched)
    assert not dlg_sched.lbl_privacy_warning.isHidden()
    assert "LÊN LỊCH PHÁT HÀNH" in dlg_sched.lbl_privacy_warning.text()


def test_overview_scheduled_upload_flow_and_history_sync(qtbot, test_container, tmp_path):
    """Test that scheduled upload records properly and appears in Scheduled tab."""
    from app.contracts import ChannelInfo, UploadResult
    from app.services.youtube.service import YouTubeService

    # Configure authenticated non-fake channel
    test_container.youtube = Mock(spec=YouTubeService)
    test_container.youtube.list_accounts.return_value = []
    test_container.connection.set_channel(ChannelInfo("UC" + "b" * 22, "Kênh Hẹn Giờ"))

    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    page = window.page_dashboard

    video = tmp_path / "scheduled_clip.mp4"
    video.write_bytes(b"sample mp4")
    window.job_state.set_local_file(video)

    page.edit_title.setText("Video Lên Lịch Tự Động Test")
    page.radio_kids_no.click()
    page.chk_rights.setChecked(True)

    # Set to scheduled mode + 2 hours
    page.radio_publish_schedule.setChecked(True)
    sched_dt = datetime.now() + timedelta(hours=2)
    page.dt_publish.setDateTime(sched_dt)

    assert page.btn_upload.isEnabled()
    assert page.btn_upload.text() in ("Hẹn giờ đăng", "Lên lịch đăng YouTube")

    # Simulate upload finished callback
    result = UploadResult(
        video_id="v" * 11,
        url="https://www.youtube.com/watch?v=" + "v" * 11,
        channel_id="UC" + "b" * 22,
        status=JobStatus.SCHEDULED,
    )
    page._on_upload_finished(result)

    # Check status message
    assert "Đã lên lịch phát hành" in page.lbl_upload_status.text()
    assert "đã công khai" not in page.lbl_upload_status.text()

    # Verify record in scheduled list
    scheduled_items = test_container.history.list_scheduled()
    assert len(scheduled_items) >= 1
    assert any(r.get("youtube_video_id") == "v" * 11 for r in scheduled_items)

    # Switch to History page and check Scheduled tab
    window.btn_nav_history.click()
    window.page_history.tab_widget.setCurrentIndex(1)
    window.page_history.refresh_scheduled()
    assert window.page_history.tbl_scheduled.rowCount() >= 1


def test_settings_real_db_path_displayed(qtbot, test_container):
    """Test that Settings page displays real app.db path and not hardcoded studio.db."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)

    db_text = window.page_settings.lbl_db_path.text()
    assert "studio.db" not in db_text
    assert "app.db" in db_text


def test_youtube_channels_page_empty_state_handling(qtbot, test_container):
    """Test YouTubeChannelsPage correctly shows EmptyState without crash when accounts is empty."""
    test_container.youtube.list_accounts = Mock(return_value=[])

    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    yt_page = window.page_youtube_channels

    yt_page._on_accounts_loaded([])
    assert yt_page._selected_account is None
    assert yt_page.stat_subscribers.lbl_value.text() == "—"
