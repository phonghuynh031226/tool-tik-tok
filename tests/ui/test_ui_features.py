"""Tests for UI features: validation, upload locking, confirmation dialog, cancellation, dry-run, history, and settings."""

import os
from pathlib import Path
from time import sleep
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.contracts import JobStatus, UploadRequest
from app.core.paths import project_root
from app.services.fakes import (
    FakeContentGenerator, FakeHistoryRepository, FakeSecretStore,
    FakeSettingsStore, FakeTikTokService, FakeYouTubeService,
)
from app.ui.components import UploadConfirmDialog
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer
from app.workers import DownloadVideoWorker, TaskWorker, UploadYouTubeWorker, YtDlpUpdateWorker


@pytest.fixture(autouse=True)
def mock_dummy_media_decode(monkeypatch):
    # These are form/worker tests with arbitrary bytes, not media playback tests.
    from app.ui.components.video_player import VideoPlayerWidget
    monkeypatch.setattr(VideoPlayerWidget, 'load_video', lambda self, path: None)


@pytest.fixture
def test_container(tmp_path):
    secrets = FakeSecretStore()
    settings = FakeSettingsStore()
    return ServiceContainer(
        tiktok=FakeTikTokService(),
        generator=FakeContentGenerator(),
        youtube=FakeYouTubeService(),
        history=FakeHistoryRepository(),
        secrets=secrets,
        settings=settings,
    )


def test_title_validation_and_upload_button_locking(qtbot, test_container, tmp_path):
    """Test validation of title, locking of upload button until Made for Kids and rights are set."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    window.show()

    dashboard = window.page_dashboard

    # This test isolates content validation. Fake services may only simulate;
    # real upload additionally requires the authenticated shared channel.
    dashboard.chk_dry_run.setChecked(True)

    # Initially, upload button is disabled
    assert not dashboard.btn_upload.isEnabled()

    # Provide a local video
    fake_video = tmp_path / "test_vid.mp4"
    fake_video.write_bytes(b"content")
    window.job_state.set_local_file(fake_video)

    # Title is set, but neither Made for Kids nor Rights confirmed
    dashboard.edit_title.setText("Tiêu đề hợp lệ")
    assert not dashboard.btn_upload.isEnabled()

    # Select Made for Kids
    dashboard.radio_kids_no.click()
    assert not dashboard.btn_upload.isEnabled()  # Still missing rights

    # Uncheck Made for Kids (exclusive check), check Rights
    dashboard.chk_rights.click()
    assert dashboard.btn_upload.isEnabled()  # Now title, kids, rights and video are all valid!

    # Title empty -> button locks again
    dashboard.edit_title.setText("")
    assert not dashboard.btn_upload.isEnabled()

    # Title > 100 characters -> button locks
    dashboard.edit_title.setText("A" * 101)
    assert not dashboard.btn_upload.isEnabled()

    # Title contains < or > -> button locks
    dashboard.edit_title.setText("Tiêu đề <không hợp lệ>")
    assert not dashboard.btn_upload.isEnabled()

    # Valid title restores button
    dashboard.edit_title.setText("Tiêu đề hoàn toàn hợp lệ")
    assert dashboard.btn_upload.isEnabled()


def test_upload_confirm_dialog_acceptance(qtbot, tmp_path):
    """Test confirmation dialog acceptance."""
    fake_video = tmp_path / "vid.mp4"
    fake_video.write_bytes(b"data")

    req = UploadRequest(
        path=fake_video,
        title="Tiêu đề video YouTube",
        description="Mô tả",
        tags=["test"],
        privacy="private",
        made_for_kids=False,
        rights_confirmed=True,
    )

    dialog = UploadConfirmDialog(req, "Kênh test", "chan-001", dry_run=False)
    qtbot.addWidget(dialog)

    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog.btn_confirm.click()
    assert accepted == [True]


def test_upload_confirm_dialog_rejection(qtbot, tmp_path):
    """Test confirmation dialog rejection."""
    fake_video = tmp_path / "vid.mp4"
    fake_video.write_bytes(b"data")

    req = UploadRequest(
        path=fake_video,
        title="Tiêu đề video YouTube",
        description="Mô tả",
        tags=["test"],
        privacy="private",
        made_for_kids=False,
        rights_confirmed=True,
    )

    dialog = UploadConfirmDialog(req, "Kênh test", "chan-001", dry_run=False)
    qtbot.addWidget(dialog)

    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog.btn_cancel.click()
    assert rejected == [True]


def test_upload_confirm_dialog_dry_run_ui(qtbot, tmp_path):
    """Test confirmation dialog in dry-run mode."""
    fake_video = tmp_path / "vid.mp4"
    fake_video.write_bytes(b"data")

    req = UploadRequest(
        path=fake_video,
        title="Tiêu đề video YouTube",
        description="Mô tả",
        tags=["test"],
        privacy="private",
        made_for_kids=False,
        rights_confirmed=True,
    )

    dialog = UploadConfirmDialog(req, "Kênh test", "chan-001", dry_run=True)
    qtbot.addWidget(dialog)

    assert "DRY-RUN" in dialog.windowTitle()
    assert "Dry-run" in dialog.btn_confirm.text()


def test_dry_run_mode_execution(qtbot, test_container, tmp_path):
    """Test that Dry-run mode runs entire flow without calling real youtube.upload()."""
    test_container.youtube.connect()
    # Mock upload to verify it is NOT called
    test_container.youtube.upload = MagicMock()

    window = MainWindow(services=test_container)
    qtbot.addWidget(window)

    dashboard = window.page_dashboard

    fake_video = tmp_path / "vid_dry.mp4"
    fake_video.write_bytes(b"video bytes")
    window.job_state.set_local_file(fake_video)
    dashboard.edit_title.setText("Video chạy thử")
    dashboard.radio_kids_no.click()
    dashboard.chk_rights.click()

    # Enable dry-run
    dashboard.chk_dry_run.click()
    assert window.job_state.dry_run is True
    assert "Dry-run" in dashboard.btn_upload.text()

    # Mock dialog exec to accept automatically
    with patch("app.ui.pages.dashboard.UploadConfirmDialog") as mock_dlg_cls:
        mock_dlg_cls.DialogCode = UploadConfirmDialog.DialogCode
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = UploadConfirmDialog.DialogCode.Accepted
        mock_dlg_cls.return_value = mock_dlg
        dashboard.btn_upload.click()

    # Wait until finished
    qtbot.waitUntil(lambda: window.job_state.dry_run_result is not None, timeout=3000)

    # Real youtube.upload was NEVER called
    test_container.youtube.upload.assert_not_called()
    assert window.job_state.upload_result is None
    assert window.job_state.status != JobStatus.UPLOADED
    assert not getattr(window.job_state.dry_run_result, 'url', None)


def test_cancel_download_and_upload_workers(qtbot, test_container, tmp_path):
    """Test cooperative cancellation of workers."""
    pool = QThreadPool.globalInstance()

    # 1. Download Worker cancellation
    meta = test_container.tiktok.fetch_metadata("https://tiktok.com/@test/1")
    dl_worker = DownloadVideoWorker(test_container.tiktok, meta, tmp_path)
    cancelled_signals = []
    dl_worker.signals.cancelled.connect(lambda: cancelled_signals.append("download"))

    pool.start(dl_worker)
    dl_worker.cancel()

    qtbot.waitUntil(lambda: len(cancelled_signals) == 1, timeout=3000)
    assert cancelled_signals == ["download"]

    # 2. Upload Worker cancellation
    test_container.youtube.connect()
    fake_video = tmp_path / "fake.mp4"
    fake_video.write_bytes(b"123")
    req = UploadRequest(
        path=fake_video,
        title="Title",
        description="Desc",
        tags=[],
        rights_confirmed=True,
    )
    up_worker = UploadYouTubeWorker(test_container.youtube, req)
    up_cancels = []
    up_worker.signals.cancelled.connect(lambda: up_cancels.append("upload"))

    pool.start(up_worker)
    up_worker.cancel()

    qtbot.waitUntil(lambda: len(up_cancels) == 1, timeout=3000)
    assert up_cancels == ["upload"]


def test_ui_unresponsive_guard_with_background_worker(qtbot):
    """Test that UI remains responsive and emits progress while background task executes."""
    pool = QThreadPool.globalInstance()
    progress_calls = []

    def long_task(on_progress, cancel_token):
        for i in range(5):
            cancel_token.raise_if_cancelled()
            sleep(0.02)
            on_progress((i + 1) / 5)
        return "DONE"

    worker = TaskWorker(long_task)
    worker.signals.progress.connect(progress_calls.append)
    results = []
    worker.signals.finished.connect(results.append)

    pool.start(worker)

    # UI can still process events and does not freeze
    qtbot.waitUntil(lambda: len(results) == 1, timeout=3000)
    assert results == ["DONE"]
    assert len(progress_calls) >= 5
    assert 1.0 in progress_calls


def test_history_page_csv_export_and_resume(qtbot, test_container, tmp_path):
    """Test History search, CSV export with utf-8-sig, and resuming an incomplete job."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    history_page = window.page_history

    # Add sample records
    test_container.history.add({
        "video_id": "vid-history-1",
        "title": "Video đang dở dang",
        "url": "https://tiktok.com/@demo/video/1",
        "status": JobStatus.DOWNLOADED,
        "privacy": "private",
        "path": str(tmp_path / "downloaded.mp4"),
    })
    history_page.refresh_history()

    assert history_page.table.rowCount() == 1

    # Test CSV Export
    csv_out = tmp_path / "test_export.csv"
    with patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv_out), "CSV Files (*.csv)")):
        with patch.object(QMessageBox, "information"):
            history_page._export_csv()

    assert csv_out.exists()
    content = csv_out.read_text(encoding="utf-8-sig")
    assert "Video đang dở dang" in content
    assert "vid-history-1" in content

    # Test Resume job
    navigated = []
    history_page.navigate_requested.connect(navigated.append)

    with patch.object(QMessageBox, "information"):
        # Click Resume button on row 0
        action_widget = history_page.table.cellWidget(0, 4)
        btn_resume = action_widget.findChildren(type(action_widget))[0] if action_widget else None
        # Directly invoke resume
        history_page._resume_job(history_page._current_records[0])

    assert window.job_state.title == "Video đang dở dang"
    assert window.job_state.status == JobStatus.DOWNLOADED
    assert navigated == [0]  # Navigated to Dashboard


def test_settings_outside_project_path_warning(qtbot, test_container):
    """Test warning dialog when choosing a path outside project root."""
    window = MainWindow(services=test_container)
    qtbot.addWidget(window)
    settings_page = window.page_settings

    # Path inside project root -> no warning
    inside_path = project_root() / ".tmp" / "test_dir"
    assert settings_page._check_and_confirm_outside_project_path(inside_path) is True

    # Path outside project root -> triggers warning dialog
    outside_path = Path("C:/Windows/Temp") if os.name == "nt" else Path("/tmp/outside")

    # If user rejects
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
        assert settings_page._check_and_confirm_outside_project_path(outside_path) is False

    # If user confirms
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
        assert settings_page._check_and_confirm_outside_project_path(outside_path) is True


def test_settings_ytdlp_update_worker(qtbot):
    """Test yt-dlp update worker runs in background and reports version."""
    worker = YtDlpUpdateWorker()
    results = []
    worker.signals.finished.connect(results.append)

    pool = QThreadPool.globalInstance()
    pool.start(worker)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=3000)
    assert "yt-dlp" in results[0]
