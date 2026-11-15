from unittest.mock import Mock
import logging

import pytest
from PySide6.QtWidgets import QLabel

from app.contracts import ChannelInfo
from app.errors import AuthExpired
from app.ui.services import ServiceContainer
from app.ui.main_window import MainWindow

CHANNEL = ChannelInfo('UC' + 'a' * 22, 'Kênh thật từ API mock')


def test_default_factory_is_real(monkeypatch):
    from app.ui import services
    monkeypatch.delenv('STUDIO_USE_FAKES', raising=False)
    monkeypatch.setattr(services, '_default_container', None)
    real = Mock()
    monkeypatch.setattr(ServiceContainer, 'create_default', Mock(return_value=real))
    monkeypatch.setattr(ServiceContainer, 'create_fake', Mock(side_effect=AssertionError('No implicit fake')))
    assert services.get_services() is real


def test_ui_starts_disconnected_without_connecting(qtbot):
    container = ServiceContainer.create_fake()
    container.youtube.connect = Mock(side_effect=AssertionError('No automatic OAuth'))
    window = MainWindow(container)
    qtbot.addWidget(window)
    assert 'Chưa kết nối' in window.page_settings.lbl_yt_channel_name.text()
    assert not window.page_dashboard.btn_upload.isEnabled()
    assert any('CHẾ ĐỘ GIẢ LẬP' in label.text() for label in window.findChildren(QLabel))


def test_shared_channel_updates_and_disconnect(qtbot):
    container = ServiceContainer.create_fake()
    window = MainWindow(container)
    qtbot.addWidget(window)
    container.connection.set_channel(CHANNEL)
    assert CHANNEL.title in window.page_settings.lbl_yt_channel_name.text()
    assert CHANNEL.id in window.page_dashboard.lbl_channel_id.text()
    assert CHANNEL.title in window.page_dashboard.lbl_channel_title.text()
    window.page_settings._disconnect_youtube()
    assert container.connection.channel is None
    assert 'Chưa kết nối' in window.page_dashboard.lbl_channel_title.text()


def test_upload_requires_authenticated_channel_even_with_valid_content(qtbot, tmp_path):
    from app.services.youtube.service import YouTubeService
    container = ServiceContainer.create_fake()
    container.youtube = YouTubeService(secret_store=container.secrets)
    window = MainWindow(container)
    qtbot.addWidget(window)
    video = tmp_path / 'sample.mp4'
    video.write_bytes(b'fake video')
    window.job_state.set_local_file(video)
    window.page_dashboard.edit_title.setText('Tiêu đề hợp lệ')
    window.page_dashboard.radio_kids_no.click()
    window.page_dashboard.chk_rights.click()
    assert not window.page_dashboard.btn_upload.isEnabled()
    container.connection.set_channel(CHANNEL)
    assert window.page_dashboard.btn_upload.isEnabled()
    container.connection.clear()
    assert not window.page_dashboard.btn_upload.isEnabled()


def test_explicit_environment_flag_selects_fake(monkeypatch):
    from app.ui import services
    monkeypatch.setattr(services, '_default_container', None)
    monkeypatch.setenv('STUDIO_USE_FAKES', '1')
    assert services.get_services().is_fake


def test_connect_worker_calls_connect_then_get_channel(qtbot):
    from app.workers.service_workers import YouTubeConnectWorker
    service = Mock()
    service.get_channel.return_value = CHANNEL
    worker = YouTubeConnectWorker(service)
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()
    service.connect.assert_called_once()
    service.get_channel.assert_called_once()
    assert results == [CHANNEL]


def test_settings_connect_uses_worker_and_publishes_channel(qtbot):
    from app.services.youtube.service import YouTubeService
    container = ServiceContainer.create_fake()
    container.youtube = Mock(spec=YouTubeService)
    container.youtube.get_channel.return_value = CHANNEL
    container.youtube.list_accounts.return_value = []
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.page_settings._connect_youtube()
    qtbot.waitUntil(lambda: container.connection.channel is not None, timeout=3000)
    container.youtube.connect.assert_called_once()
    assert CHANNEL.title in window.page_settings.lbl_yt_channel_name.text()
    assert CHANNEL.id in window.page_dashboard.lbl_channel_id.text()


@pytest.mark.parametrize('contents', ['{broken', '{"web": {}}'])
def test_bad_client_json_is_rejected_safely(tmp_path, contents):
    from app.services.youtube.auth import import_client_secret
    from app.errors import ContentInvalid
    container = ServiceContainer.create_fake()
    selected = tmp_path / 'client.json'
    selected.write_text(contents, encoding='utf-8')
    with pytest.raises(ContentInvalid) as caught:
        import_client_secret(selected, container.secrets)
    assert 'Desktop' in caught.value.user_message


@pytest.mark.parametrize('code,description,expected', [
    ('access_denied', 'User denied access', 'từ chối'),
    ('access_denied', 'app in testing, user is not a test user', 'Test users'),
    ('invalid_client', 'dummy secret must not leak', 'Desktop'),
    ('timeout', 'dummy secret must not leak', 'thời gian'),
    ('network', 'dummy secret must not leak', 'mạng'),
])
def test_oauth_errors_are_safe_and_specific(code, description, expected):
    from app.services.youtube.auth import oauth_error
    error = RuntimeError(description)
    error.error = code
    result = oauth_error(error)
    assert expected in result.user_message
    assert 'dummy secret' not in result.user_message


def test_logging_creates_redacted_file_immediately(tmp_path):
    from app.security.logging import configure_logging
    path = tmp_path / 'startup.log'
    logger = configure_logging(path)
    try:
        assert path.exists() and path.stat().st_size > 0
        logger.info('access_token=%s', 'dummy-private-value')
        for handler in logger.handlers: handler.flush()
        assert 'dummy-private-value' not in path.read_text(encoding='utf-8')
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
