from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel

from app.contracts import ChannelInfo, JobStatus, UploadRequest
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer
from app.ui.components import UploadConfirmDialog
from app.ui.state import JobState
from app.workers.service_workers import UploadYouTubeWorker


def request(tmp_path):
    path = tmp_path / 'sample.mp4'
    path.write_bytes(b'dummy')
    return UploadRequest(path, 'Video thử', 'Mô tả', [], made_for_kids=False, rights_confirmed=True)


def test_dry_run_has_no_video_identity_or_history(qtbot, tmp_path):
    container = ServiceContainer.create_fake()
    container.youtube.upload = Mock(side_effect=AssertionError('No real upload'))
    window = MainWindow(container)
    qtbot.addWidget(window)
    req = request(tmp_path)
    worker = UploadYouTubeWorker(container.youtube, req, dry_run=True, confirmed_channel_id='test-channel')
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()
    result = results[0]
    assert not getattr(result, 'url', None) and not getattr(result, 'video_id', None)
    window.page_dashboard._on_upload_finished(result)
    assert window.job_state.status != JobStatus.UPLOADED
    assert window.job_state.upload_result is None
    assert window.lbl_active_job_status.text() == 'Đã chạy thử (chưa đăng YouTube)'
    assert container.history.list() == []
    assert window.page_dashboard.lbl_upload_url.isHidden()
    assert window.page_dashboard.btn_open_youtube.isHidden()
    assert window.page_dashboard.btn_copy_link.isHidden()
    assert window.page_youtube.lbl_result_link.isHidden()
    assert window.page_youtube.btn_open.isHidden() and window.page_youtube.btn_copy.isHidden()
    assert 'Video thử' in window.page_dashboard.lbl_upload_summary.text()


def test_private_on_start_and_reset_even_with_saved_public(qtbot):
    container = ServiceContainer.create_fake()
    container.settings.set('default_privacy', 'public')
    window = MainWindow(container)
    qtbot.addWidget(window)
    assert window.job_state.privacy == 'private'
    assert window.page_dashboard.combo_privacy.currentData() == 'private'
    assert window.page_settings.combo_def_privacy.currentData() == 'private'
    window.job_state.privacy = 'public'
    window.job_state.reset()
    assert window.page_dashboard.combo_privacy.currentData() == 'private'


@pytest.mark.parametrize('privacy', ['public', 'unlisted'])
def test_visibility_warning_is_prominent(qtbot, tmp_path, privacy):
    req = request(tmp_path)
    req.privacy = privacy
    dialog = UploadConfirmDialog(req, 'Kênh', 'channel')
    qtbot.addWidget(dialog)
    assert privacy.upper() in dialog.lbl_privacy_warning.text()
    assert 'background' in dialog.lbl_privacy_warning.styleSheet()


def test_channel_indicator_tracks_connection(qtbot):
    container = ServiceContainer.create_fake()
    from app.services.youtube.service import YouTubeService
    container.youtube = YouTubeService(secret_store=container.secrets)
    window = MainWindow(container)
    qtbot.addWidget(window)
    indicator = window.page_dashboard.lbl_channel_indicator
    assert indicator.property('connectionState') == 'disconnected'
    container.connection.busy = True
    container.connection.changed.emit()
    assert indicator.property('connectionState') == 'checking'
    container.connection.busy = False
    container.connection.set_channel(ChannelInfo('UC' + 'a' * 22, 'Mock API channel'))
    assert indicator.property('connectionState') == 'connected'


def test_hashtags_and_complete_description_byte_limit(tmp_path):
    state = JobState()
    state.set_local_file(request(tmp_path).path)
    state.title = 'Title'
    state.rights_confirmed = True
    state.made_for_kids = False
    state.hashtags = ['Python', '#GeminiAPI']
    assert '#Python #GeminiAPI' in state.build_upload_request().description
    state.description = 'ế' * 1666
    assert not state.can_upload()[0]


def test_hashtags_are_prefixed_in_both_editors(qtbot):
    from app.contracts import GeneratedContent
    window = MainWindow(ServiceContainer.create_fake())
    qtbot.addWidget(window)
    window.job_state.set_generated_content(GeneratedContent('Title', 'Desc', ['Python', 'GeminiAPI'], []))
    assert window.page_dashboard.edit_hashtags.text() == '#Python #GeminiAPI'
    assert window.page_ai.edit_hashtags.text() == '#Python #GeminiAPI'


def test_old_dry_run_history_is_not_shown_as_published(qtbot):
    container = ServiceContainer.create_fake()
    container.history.add({'video_id': 'dry-run-001', 'url': 'legacy-placeholder', 'status': JobStatus.UPLOADED})
    window = MainWindow(container)
    qtbot.addWidget(window)
    page = window.page_history
    page.refresh_history()
    assert page.table.item(0, 2).text() == 'Chạy thử'
    assert not page._current_records[0]['url']
    assert not page._current_records[0]['youtube_video_id']


def test_event_logging_for_content_connect_and_dry_run(qtbot, tmp_path):
    from app.security.logging import configure_logging
    from app.contracts import GeneratedContent
    from app.workers.service_workers import YouTubeConnectWorker
    path = tmp_path / 'events.log'
    logger = configure_logging(path)
    try:
        state = JobState()
        state.set_generated_content(GeneratedContent('Title', 'Desc', [], []))
        service = Mock()
        service.get_channel.return_value = ChannelInfo('UC' + 'a' * 22, 'Mock channel')
        YouTubeConnectWorker(service).run()
        UploadYouTubeWorker(service, request(tmp_path), dry_run=True).run()
        for handler in logger.handlers: handler.flush()
        text = path.read_text(encoding='utf-8')
        assert all(event in text for event in ['content_generated', 'youtube_connected', 'dry_run_completed'])
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
