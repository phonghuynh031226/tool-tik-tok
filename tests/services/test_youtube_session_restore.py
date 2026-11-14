from unittest.mock import Mock
import json

import pytest
from google.auth.exceptions import RefreshError, TransportError

from app.errors import AuthExpired, NetworkError
from app.services.youtube import auth, service
from tests.services.test_youtube_service import MemorySecrets, CHANNEL


@pytest.fixture
def saved_session(monkeypatch):
    secrets = MemorySecrets()
    secrets.set(auth.CLIENT_KEY, 'client-remains-in-secret-store')
    secrets.set(auth.TOKEN_KEY, 'stored-token-json')
    credentials = Mock(expired=False, valid=True)
    credentials.to_json.return_value = '{"refresh_token":"dummy-refresh-only"}'
    monkeypatch.setattr(auth, 'load_credentials', Mock(return_value=credentials))
    browser = Mock(side_effect=AssertionError('Startup must not authorize/open a browser'))
    monkeypatch.setattr(auth, 'authorize', browser)
    monkeypatch.setattr('webbrowser.get', browser)
    monkeypatch.setattr('httplib2.Http.request', Mock(side_effect=AssertionError('No network')))
    api = Mock()
    api.channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': CHANNEL, 'snippet': {'title': 'Restored API channel'}}]}
    monkeypatch.setattr(service, 'build', Mock(return_value=api))
    return service.YouTubeService(secret_store=secrets), secrets, credentials, api, browser


def test_restore_valid_session_without_browser(saved_session):
    youtube, secrets, credentials, api, browser = saved_session
    assert youtube.restore_session().id == CHANNEL
    credentials.refresh.assert_not_called()
    browser.assert_not_called()


def test_restore_without_token_does_not_authorize(saved_session):
    youtube, secrets, _, api, browser = saved_session
    secrets.delete(auth.TOKEN_KEY)
    auth.load_credentials.return_value = None
    assert youtube.restore_session() is None
    api.channels.assert_not_called()
    browser.assert_not_called()


def test_restore_refresh_success_persists_refresh_token(saved_session):
    youtube, secrets, credentials, _, browser = saved_session
    credentials.expired = True
    credentials.refresh.side_effect = lambda request: setattr(credentials, 'expired', False)
    assert youtube.restore_session().id == CHANNEL
    credentials.refresh.assert_called_once()
    assert json.loads(secrets.get(auth.TOKEN_KEY))['refresh_token'] == 'dummy-refresh-only'
    browser.assert_not_called()


def test_restore_revoked_refresh_clears_token_retains_client(saved_session):
    youtube, secrets, credentials, _, browser = saved_session
    credentials.expired = True
    credentials.refresh.side_effect = RefreshError('invalid_grant dummy-private-diagnostic')
    with pytest.raises(AuthExpired) as caught:
        youtube.restore_session()
    assert caught.value.user_message == auth.SESSION_EXPIRED_MESSAGE
    assert secrets.get(auth.TOKEN_KEY) is None
    assert secrets.get(auth.CLIENT_KEY) == 'client-remains-in-secret-store'
    assert 'dummy-private' not in caught.value.user_message
    browser.assert_not_called()


def test_restore_network_failure_retains_token(saved_session):
    youtube, secrets, credentials, _, browser = saved_session
    credentials.expired = True
    credentials.refresh.side_effect = TransportError('temporary transport failure')
    with pytest.raises(NetworkError): youtube.restore_session()
    assert secrets.get(auth.TOKEN_KEY) == 'stored-token-json'
    browser.assert_not_called()


def test_disconnect_prevents_restore_on_next_instance(saved_session, monkeypatch):
    youtube, secrets, _, api, browser = saved_session
    youtube.disconnect()
    monkeypatch.setattr(auth, 'load_credentials', lambda store: None if store.get(auth.TOKEN_KEY) is None else Mock())
    reopened = service.YouTubeService(secret_store=secrets)
    assert reopened.restore_session() is None
    assert secrets.get(auth.CLIENT_KEY)
    browser.assert_not_called()


def test_credentials_round_trip_in_secret_store_includes_refresh_token():
    from google.oauth2.credentials import Credentials
    secrets = MemorySecrets()
    credentials = Credentials(token='dummy-access', refresh_token='dummy-refresh',
        token_uri='https://oauth2.googleapis.com/token', client_id='dummy-client',
        client_secret='dummy-client-secret', scopes=auth.SCOPES)
    auth.save_credentials(credentials, secrets)
    restored = auth.load_credentials(secrets)
    assert restored.refresh_token == 'dummy-refresh'
    assert restored.client_id == 'dummy-client'


def test_reconnect_after_rejected_restore_uses_saved_client(saved_session, monkeypatch):
    youtube, secrets, credentials, _, _ = saved_session
    credentials.expired = True
    credentials.refresh.side_effect = RefreshError('invalid_grant')
    with pytest.raises(AuthExpired): youtube.restore_session()
    monkeypatch.setattr(auth, 'load_credentials', lambda store: None)
    fresh = Mock(expired=False, valid=True)
    authorize = Mock(return_value=fresh)
    monkeypatch.setattr(auth, 'authorize', authorize)
    assert youtube.connect().id == CHANNEL
    authorize.assert_called_once_with(secrets)
    assert secrets.get(auth.CLIENT_KEY) == 'client-remains-in-secret-store'


def test_window_without_token_remains_disconnected(saved_session, qtbot):
    from app.ui.services import ServiceContainer
    from app.ui.main_window import MainWindow
    youtube, secrets, _, _, browser = saved_session
    secrets.delete(auth.TOKEN_KEY)
    auth.load_credentials.return_value = None
    container = ServiceContainer.create_fake()
    container.youtube = youtube
    window = MainWindow(container)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: container.connection._restore_started and not container.connection.busy, timeout=3000)
    assert 'Chưa kết nối' in window.page_settings.lbl_yt_channel_name.text()
    assert container.connection.channel is None
    assert not window.page_youtube.btn_upload.isEnabled()
    browser.assert_not_called()


def test_window_restores_in_background_and_displays_channel(saved_session, qtbot):
    from app.ui.services import ServiceContainer
    from app.ui.main_window import MainWindow
    youtube, _, _, _, browser = saved_session
    container = ServiceContainer.create_fake()
    container.youtube = youtube
    window = MainWindow(container)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: container.connection.channel is not None, timeout=3000)
    assert CHANNEL in window.page_settings.lbl_yt_channel_id.text()
    assert 'Restored API channel' in window.page_dashboard.lbl_channel_title.text()
    assert window.page_dashboard.lbl_channel_indicator.property('connectionState') == 'connected'
    browser.assert_not_called()


def test_window_restore_rejected_shows_expired_message(saved_session, qtbot):
    from app.ui.services import ServiceContainer
    from app.ui.main_window import MainWindow
    youtube, secrets, credentials, _, browser = saved_session
    credentials.expired = True
    credentials.refresh.side_effect = RefreshError('invalid_grant')
    container = ServiceContainer.create_fake()
    container.youtube = youtube
    window = MainWindow(container)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: auth.SESSION_EXPIRED_MESSAGE in window.page_settings.lbl_yt_channel_id.text(), timeout=3000)
    assert container.connection.channel is None
    assert not window.page_dashboard.btn_upload.isEnabled()
    assert secrets.get(auth.TOKEN_KEY) is None
    browser.assert_not_called()
