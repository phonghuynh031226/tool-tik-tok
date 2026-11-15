"""Real backend + SQLite + Qt workers; Google/OAuth and secrets are mocked."""
import logging
from datetime import datetime, timedelta
from unittest.mock import Mock

from app.contracts import JobStatus
from app.db.repository import SQLiteHistoryRepository
from app.db.stats_cache import SQLiteStatsCache
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer
from tests.services.test_youtube_accounts import accounts, credentials, A
from tests.services.test_youtube_service import VIDEO


def test_add_stats_schedule_sync_via_real_backend_and_ui(accounts, qtbot, monkeypatch, caplog):
    from app.services.youtube import service
    from app.ui.components import UploadConfirmDialog
    youtube, secrets, settings, authorized, clients, tmp_path = accounts
    history = SQLiteHistoryRepository(tmp_path / 'app.db', secret_store=secrets)
    youtube._history_repository = history
    youtube._stats_cache = SQLiteStatsCache(history.path)
    public = {'value': False}
    original_build = service.build
    def build(*args, **kwargs):
        api = original_build(*args, **kwargs)
        api.channels.return_value.list.return_value.execute.return_value['items'][0].update(
            statistics={'subscriberCount': '12300', 'viewCount': '45678', 'videoCount': '1'},
            contentDetails={'relatedPlaylists': {'uploads': 'UU-test'}})
        api.playlistItems.return_value.list.return_value.execute.return_value = {
            'items': [{'contentDetails': {'videoId': VIDEO}}]}
        api.videos.return_value.list.return_value.execute.side_effect = lambda **kw: {'items': [{
            'id': VIDEO, 'snippet': {'channelId': A, 'title': 'API video', 'publishedAt': '2026-01-01T00:00:00Z'},
            'statistics': {'viewCount': '100'}, 'contentDetails': {'duration': 'PT12S'},
            'status': {'privacyStatus': 'public' if public['value'] else 'private', 'uploadStatus': 'processed'}}]}
        return api
    monkeypatch.setattr(service, 'build', build)
    monkeypatch.setattr(UploadConfirmDialog, 'exec', lambda self: self.DialogCode.Accepted)
    monkeypatch.setattr('PySide6.QtWidgets.QMessageBox.warning', Mock(side_effect=AssertionError('Unexpected warning')))
    container = ServiceContainer.create_fake()
    container.youtube, container.history, container.secrets, container.settings = youtube, history, secrets, settings
    window = MainWindow(container)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: container.connection._restore_started and not container.connection.busy)
    page = window.page_dashboard
    assert not page.btn_upload.isEnabled() and not page.chk_rights.isChecked()
    assert not page.radio_kids_yes.isChecked() and not page.radio_kids_no.isChecked()
    authorized.append(credentials(A))
    with caplog.at_level(logging.INFO):
        window.page_youtube_channels._on_add_account()
        qtbot.waitUntil(lambda: container.connection.channel is not None, timeout=5000)
        qtbot.waitUntil(lambda: window.page_youtube_channels.stat_subscribers.lbl_value.text() == '12,300', timeout=5000)
        assert container.connection.channel.title == 'RAYKI VN'
        path = tmp_path / 'selected.mp4'
        path.write_bytes(b'mocked-mp4')
        window.job_state.set_local_file(path)
        page.edit_title.setText('Video scheduled through UI')
        page.radio_kids_no.click()
        assert not page.btn_upload.isEnabled()
        page.chk_rights.setChecked(True)
        page.radio_publish_schedule.setChecked(True)
        page.dt_publish.setDateTime(datetime.now() + timedelta(hours=2))
        assert page.btn_upload.isEnabled()
        page._on_upload_clicked()
        qtbot.waitUntil(lambda: window.job_state.status == JobStatus.SCHEDULED and not container.connection.busy, timeout=5000)
        request_body = clients[A][0].videos.return_value.insert.call_args.kwargs['body']
        assert request_body['status']['privacyStatus'] == 'private'
        assert request_body['status']['publishAt'].endswith('Z')
        assert window.job_state.channel_id == A
        assert 'chưa xác nhận công khai' in window.lbl_active_job_status.text()
        assert 'Đã lên lịch' in page.lbl_upload_status.text()
        assert len(history.list()) == 1
        history_page = window.page_history
        history_page.refresh_scheduled()
        assert history_page.tbl_scheduled.rowCount() == 1
        history_page.btn_refresh_scheduled.click()
        qtbot.waitUntil(lambda: history_page.btn_sync_scheduled.isEnabled(), timeout=5000)
        assert history.list_scheduled()[0]['uploaded_at'] is None
        public['value'] = True
        history_page.btn_refresh_scheduled.click()
        qtbot.waitUntil(lambda: not history.list_scheduled(), timeout=5000)
        qtbot.waitUntil(lambda: history_page.btn_sync_scheduled.isEnabled(), timeout=5000)
        record = history.list()[0]
        assert record['processing_status'] == JobStatus.UPLOADED
        assert record['schedule_public_confirmed'] is True and record['uploaded_at']
        assert history_page.tbl_scheduled.cellWidget(0, 5).lbl_text.text() == 'Đã công khai'
    assert str(history.path) == window.page_settings.lbl_db_path.text()
    assert 'CHẾ ĐỘ GIẢ LẬP' not in ''.join(label.text() for label in window.findChildren(__import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel))
    for secret in ('access-' + A, 'refresh-' + A, 'test-client-secret'):
        assert secret not in caplog.text
    history.close()


def test_startup_verifies_all_accounts_without_blocking_or_opening_browser(qtbot, monkeypatch):
    import threading
    from PySide6.QtCore import QTimer
    from app.contracts import ChannelAccount
    from app.errors import AuthExpired
    release = threading.Event()
    calls = []
    main_thread = threading.get_ident()
    b = 'UC' + 'b' * 22
    accounts = [ChannelAccount(A, 'Expired default', is_default=True, status='expired'),
                ChannelAccount(b, 'Verified second', status='connected')]
    class WaitingBackend:
        def list_accounts(self):
            calls.append(threading.get_ident())
            assert release.wait(5)
            return accounts
        def restore_session(self):
            raise AuthExpired()
    monkeypatch.setattr('webbrowser.open', Mock(side_effect=AssertionError('No startup OAuth')))
    container = ServiceContainer.create_fake()
    container.youtube = WaitingBackend()
    window = MainWindow(container)
    qtbot.addWidget(window)
    tick = []
    QTimer.singleShot(0, lambda: tick.append(True))
    try:
        qtbot.waitUntil(lambda: bool(tick) and bool(calls), timeout=1000)
        assert not container.upload_enabled()
        assert all(thread != main_thread for thread in calls)
    finally:
        release.set()
    qtbot.waitUntil(lambda: container.connection.accounts_loaded and not container.connection.busy, timeout=5000)
    assert {a.id: a.status for a in container.connection.accounts} == {A: 'expired', b: 'connected'}
    assert not container.upload_enabled()
    container.connection.select_channel(b)
    assert container.upload_enabled() and container.connection.channel.id == b


def test_default_container_shares_real_backend_settings_and_database(monkeypatch, tmp_path):
    import app.ui.services as module
    from app.services.youtube.service import YouTubeService
    from app.security.settings import JSONSettingsStore
    from tests.services.test_youtube_service import MemorySecrets
    secrets = MemorySecrets()
    settings = JSONSettingsStore(tmp_path / 'settings.json')
    history = SQLiteHistoryRepository(tmp_path / 'app.db', secret_store=secrets)
    monkeypatch.setattr(module, 'KeyringSecretStore', lambda: secrets)
    monkeypatch.setattr(module, 'JSONSettingsStore', lambda: settings)
    monkeypatch.setattr(module, 'SQLiteHistoryRepository', lambda **kw: history)
    monkeypatch.delenv('STUDIO_USE_FAKES', raising=False)
    container = ServiceContainer.create_default()
    assert isinstance(container.youtube, YouTubeService) and not container.is_fake
    assert container.youtube._settings is settings
    assert container.youtube._history_repository is history
    history.close()


def test_backend_events_are_logged_with_secrets_redacted(tmp_path):
    from app.security.logging import configure_logging
    path = tmp_path / 'studio.log'
    app_logger = logging.getLogger('app')
    previous_level = app_logger.level
    logger = configure_logging(path, include_app=True)
    try:
        logging.getLogger('app.services.youtube.stats').info(
            'estimated_quota_units=1 access_token=%s api_key=%s', 'dummy-sensitive-token', 'dummy-sensitive-key')
        for handler in logger.handlers:
            handler.flush()
        text = path.read_text(encoding='utf-8')
        assert 'estimated_quota_units=1' in text
        assert 'dummy-sensitive-token' not in text and 'dummy-sensitive-key' not in text
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            app_logger.removeHandler(handler)
            handler.close()
        app_logger.setLevel(previous_level)


def test_late_channel_data_does_not_replace_the_selected_channel(qtbot):
    from app.contracts import ChannelAccount, ChannelStats, VideoStats
    from app.ui.pages.youtube_channels_page import YouTubeChannelsPage
    from app.ui.state import JobState
    services = ServiceContainer.create_fake()
    services.youtube.list_accounts = Mock(return_value=[])
    page = YouTubeChannelsPage(JobState(), services)
    qtbot.addWidget(page)
    b = 'UC' + 'b' * 22
    page._selected_account = ChannelAccount(b, 'Selected')
    page.stat_subscribers.set_value('Unchanged')
    page._on_stats_loaded(ChannelStats(A, 100))
    assert page.stat_subscribers.lbl_value.text() == 'Unchanged'
    page._on_channel_videos_loaded(A, [VideoStats('a' * 11, 'Wrong account')])
    assert page.tbl_videos.rowCount() == 0
    page._on_stats_loaded(ChannelStats(b, 200))
    page._on_channel_videos_loaded(b, [VideoStats('b' * 11, 'Selected account')])
    assert page.stat_subscribers.lbl_value.text() == '200'
    assert page.tbl_videos.item(0, 1).text() == 'Selected account'
