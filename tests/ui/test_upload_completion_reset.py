from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton
from app.contracts import JobStatus, UploadResult
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


@pytest.mark.parametrize('scheduled', [False, True])
def test_success_toast_history_then_fresh_form(qtbot, tmp_path, monkeypatch, scheduled):
    services = ServiceContainer.create_fake()
    from app.services.youtube.service import YouTubeService
    services.youtube = Mock(spec=YouTubeService)
    services.youtube.list_accounts.return_value = []
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    page, state = window.page_dashboard, window.job_state
    path = tmp_path / 'source.mp4'
    path.write_bytes(b'mock-video')
    state.set_local_file(path)
    state.url = 'https://www.tiktok.com/@demo/video/123'
    state.title = 'Uploaded title'
    state.description = 'Uploaded description'
    state.tags = ['tag']
    state.hashtags = ['hash']
    state.rights_confirmed = True
    state.made_for_kids = False
    if scheduled:
        page.radio_publish_schedule.setChecked(True)
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    state.publish_at = when if scheduled else None
    result = UploadResult('v' * 11, 'https://www.youtube.com/watch?v=' + 'v' * 11, 'UC' + 'b' * 22,
                          status=JobStatus.SCHEDULED if scheduled else JobStatus.UPLOADED)
    opened = Mock(return_value=True)
    monkeypatch.setattr(QDesktopServices, 'openUrl', opened)
    page._on_upload_finished(result)
    records = services.history.list()
    assert len(records) == 1
    assert records[0]['youtube_title'] == 'Uploaded title'
    assert records[0]['youtube_video_id'] == result.video_id
    assert state.status == JobStatus.NEW
    assert state.local_video_path is None and state.upload_result is None
    assert state.publish_at is None and state.privacy == 'private'
    assert state.made_for_kids is None and not state.rights_confirmed
    assert not page.input_url.text() and not page.edit_title.text()
    assert not page.edit_desc.toPlainText()
    assert page.radio_publish_now.isChecked()
    assert page.upload_result_box.isHidden() and page.progress_upload.isHidden()
    assert not page.btn_upload.isEnabled()
    assert path.exists()
    toast = window.toast_manager.toasts[-1]
    assert toast.toast_type == 'success'
    assert toast.height() >= toast.sizeHint().height()
    assert ('hẹn giờ' in toast.title_text.lower()) == scheduled
    assert result.video_id in toast.message_text
    action = next(b for b in toast.findChildren(QPushButton) if b.text() == 'Mở YouTube')
    action.click()
    assert opened.call_args.args[0].toString() == result.url


def test_history_failure_preserves_form_and_warns(qtbot):
    services = ServiceContainer.create_fake()
    from app.services.youtube.service import YouTubeService
    services.youtube = Mock(spec=YouTubeService)
    services.youtube.list_accounts.return_value = []
    services.history.add = Mock(side_effect=OSError('test failure'))
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.job_state.title = 'Keep this title'
    window.page_dashboard._on_upload_finished(UploadResult('v' * 11, 'https://www.youtube.com/watch?v=' + 'v' * 11, 'UC' + 'b' * 22))
    assert window.job_state.title == 'Keep this title'
    assert window.toast_manager.toasts[-1].toast_type == 'warning'
