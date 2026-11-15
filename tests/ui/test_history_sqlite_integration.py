from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.contracts import ChannelInfo, JobStatus, UploadResult
from app.db.repository import SQLiteHistoryRepository
from app.ui.pages.history_page import HistoryPage
from app.ui.pages.youtube_page import YouTubePage
from app.ui.services import ServiceContainer
from app.ui.state import JobState


@pytest.fixture
def container(tmp_path):
    services = ServiceContainer.create_fake()
    services.youtube = Mock()
    services.history = SQLiteHistoryRepository(tmp_path / 'history.db', secret_store=services.secrets)
    services.connection.set_channel(ChannelInfo('UC' + 'a' * 22, 'Chosen verified channel'))
    yield services
    services.history.close()


def schedule(services, **changes):
    record = dict(youtube_video_id='v' * 11, youtube_title='YouTube title',
        channel_id='UC' + 'a' * 22, scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        status=JobStatus.SCHEDULED, privacy_status='private')
    record.update(changes)
    return services.history.add(record)


def test_canonical_schedule_and_overdue_private_need_review(qtbot, container):
    schedule(container)
    page = HistoryPage(JobState(), container)
    qtbot.addWidget(page)
    assert page.tbl_scheduled.item(0, 0).text() == 'v' * 11
    assert page.tbl_scheduled.item(0, 1).text() == 'YouTube title'
    assert page.tbl_scheduled.item(0, 2).text() == 'UC' + 'a' * 22
    assert page.tbl_scheduled.cellWidget(0, 5).lbl_text.text() == 'Cần kiểm tra'


@pytest.mark.parametrize('status,privacy,confirmed,expected', [
    (JobStatus.UPLOADED, 'private', False, 'Cần kiểm tra'),
    (JobStatus.UPLOADED, 'public', False, 'Cần kiểm tra'),
    (JobStatus.UPLOADED, 'public', True, 'Đã công khai'),
    (JobStatus.SCHEDULED, 'private', False, 'Cần kiểm tra'),
])
def test_public_requires_api_confirmation_marker(qtbot, container, status, privacy, confirmed, expected):
    page = HistoryPage(JobState(), container)
    qtbot.addWidget(page)
    page._render_scheduled([dict(status=status, privacy_status=privacy,
        schedule_public_confirmed=confirmed, schedule_needs_review=True,
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    assert page.tbl_scheduled.cellWidget(0, 5).lbl_text.text() == expected


def test_refresh_button_syncs_once_and_retains_confirmed_public(qtbot, container):
    job_id = schedule(container)

    def sync():
        container.history.update(job_id, dict(status=JobStatus.UPLOADED, privacy_status='public',
            schedule_public_confirmed=True, schedule_needs_review=False))
        return [UploadResult('v' * 11, 'https://www.youtube.com/watch?v=' + 'v' * 11, 'UC' + 'a' * 22)]

    container.youtube.sync_scheduled.side_effect = sync
    page = HistoryPage(JobState(), container)
    qtbot.addWidget(page)
    page.btn_refresh_scheduled.click()
    qtbot.waitUntil(lambda: page._sync_worker is None, timeout=5000)
    assert container.youtube.sync_scheduled.call_count == 1
    assert page.btn_refresh_scheduled.isEnabled()
    assert page.tbl_scheduled.rowCount() == 1
    assert page.tbl_scheduled.cellWidget(0, 5).lbl_text.text() == 'Đã công khai'


def test_request_uses_shared_selected_channel(qtbot, container, tmp_path, monkeypatch):
    state = JobState()
    path = tmp_path / 'sample.mp4'
    path.write_bytes(b'video')
    state.set_local_file(path)
    state.title = 'Title'
    state.rights_confirmed = True
    state.made_for_kids = False
    state.channel_id = 'UC' + 'b' * 22
    page = YouTubePage(state, container)
    qtbot.addWidget(page)
    page._sync_state()
    monkeypatch.setattr('app.ui.pages.youtube_page.UploadConfirmDialog.exec', lambda self: self.DialogCode.Accepted)
    pool = Mock()
    page.thread_pool = pool
    page._on_upload()
    worker = pool.start.call_args.args[0]
    assert worker.request.channel_id == container.connection.channel.id
    container.connection.end_upload(page)


def test_scheduled_result_avoids_duplicate_backend_history(qtbot, container, tmp_path):
    schedule(container)
    state = JobState()
    path = tmp_path / 'sample.mp4'
    path.write_bytes(b'video')
    state.set_local_file(path)
    state.title = 'Title'
    page = YouTubePage(state, container)
    qtbot.addWidget(page)
    result = UploadResult('v' * 11, 'https://www.youtube.com/watch?v=' + 'v' * 11,
        'UC' + 'a' * 22, JobStatus.SCHEDULED)
    page._on_finished(result)
    assert len(container.history.list()) == 1
    assert state.status == JobStatus.SCHEDULED
    assert page.lbl_result_status.text() == 'Đã hẹn giờ'
    page._on_upload_result(UploadResult(result.video_id, result.url, result.channel_id))
    assert page.lbl_result_status.text() == 'Đã tải lên'
