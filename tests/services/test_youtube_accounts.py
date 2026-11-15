"""Account integration tests: in-memory secrets, fake HTTP and no browser/network."""
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials

from app.contracts import UploadRequest
from app.core.cancel import CancelToken
from app.errors import AccountNotFound, AuthExpired, NetworkError
from app.security.settings import JSONSettingsStore
from app.services.youtube import auth, service
from tests.services.test_youtube_service import MemorySecrets, VIDEO

A = 'UC' + 'a' * 22
B = 'UC' + 'b' * 22


def credentials(channel):
    return Credentials(token='access-' + channel, refresh_token='refresh-' + channel,
        token_uri='https://oauth2.googleapis.com/token', client_id='test-client',
        client_secret='test-client-secret', scopes=auth.SCOPES,
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None))


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    secrets = MemorySecrets()
    settings = JSONSettingsStore(tmp_path / 'settings.json')
    clients = {}
    authorized = []
    def build(*args, http, **kwargs):
        channel = http.owner._credentials.token.removeprefix('access-')
        api = Mock()
        api.channels.return_value.list.return_value.execute.return_value = {'items': [{
            'id': channel, 'snippet': {'title': 'RAYKI VN' if channel == A else 'Kênh B',
                'thumbnails': {'default': {'url': 'https://yt3.googleusercontent.com/sample'}}}}]}
        request = Mock(resumable_uri=None)
        request.next_chunk.return_value = (None, {'id': VIDEO, 'snippet': {'channelId': channel}})
        api.videos.return_value.insert.return_value = request
        clients[channel] = (api, http)
        return api
    def authorize(store):
        result = authorized.pop(0)
        auth.save_credentials(result, store)
        return result
    monkeypatch.setattr(service, 'build', build)
    monkeypatch.setattr(auth, 'authorize', Mock(side_effect=authorize))
    monkeypatch.setattr('httplib2.Http.request', Mock(side_effect=AssertionError('No network')))
    monkeypatch.setattr('requests.sessions.Session.request', Mock(side_effect=AssertionError('No network')))
    monkeypatch.setattr('webbrowser.open', Mock(side_effect=AssertionError('No browser')))
    youtube = service.YouTubeService(secret_store=secrets, settings_store=settings)
    return youtube, secrets, settings, authorized, clients, tmp_path


def test_add_duplicate_default_remove_and_reopen(accounts):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B), credentials(A)])
    assert youtube.add_account().id == A
    youtube.add_account()
    youtube.add_account()
    assert len(youtube.list_accounts()) == 2
    assert youtube.get_channel().id == A
    youtube.set_default_account(B)
    assert youtube.get_channel().id == B
    reopened = service.YouTubeService(secret_store=secrets, settings_store=settings)
    assert reopened.restore_session().id == B
    youtube.remove_account(B)
    assert secrets.get(auth.account_token_key(B)) is None
    assert youtube.get_channel().id == A
    youtube.remove_account(A)
    assert youtube.list_accounts() == [] and youtube.restore_session() is None
    assert auth.TOKEN_KEY not in secrets.values
    with pytest.raises(AccountNotFound): youtube.set_default_account(B)
    with pytest.raises(AccountNotFound): youtube.remove_account(B)


def test_legacy_token_migrates_without_authorizing(accounts):
    youtube, secrets, settings, _, _, _ = accounts
    auth.save_credentials(credentials(A), secrets)
    assert youtube.restore_session().title == 'RAYKI VN'
    assert secrets.get(auth.TOKEN_KEY) is None
    assert json.loads(secrets.get(auth.account_token_key(A)))['refresh_token'] == 'refresh-' + A
    assert settings.get('youtube_accounts')[0]['id'] == A
    assert youtube.list_accounts()[0].thumbnail_url.endswith('/sample')
    auth.authorize.assert_not_called()


def test_expired_account_does_not_break_others_or_open_browser(accounts, monkeypatch):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B)])
    youtube.add_account()
    youtube.add_account()
    secrets.delete(auth.account_token_key(A))
    youtube = service.YouTubeService(secret_store=secrets, settings_store=settings)
    authorize_count = auth.authorize.call_count
    results = {account.id: account.status for account in youtube.list_accounts()}
    assert results == {A: 'expired', B: 'connected'}
    assert auth.authorize.call_count == authorize_count
    req = UploadRequest(__file__, 'Title', 'Desc', [], rights_confirmed=True, channel_id=A)
    with pytest.raises(AuthExpired): youtube.upload(req, lambda _: None, CancelToken())


def test_explicit_upload_uses_selected_accounts_transport(accounts):
    youtube, _, _, authorized, clients, tmp_path = accounts
    authorized.extend([credentials(A), credentials(B)])
    youtube.add_account()
    youtube.add_account()
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'test-mp4')
    req = UploadRequest(path, 'Title', 'Desc', [], rights_confirmed=True, channel_id=B)
    youtube.confirm_upload(req, made_for_kids=False, channel_id=B)
    assert youtube.upload(req, lambda _: None, CancelToken()).channel_id == B
    assert clients[B][1].owner._credentials.token == 'access-' + B
    clients[A][0].videos.return_value.insert.assert_not_called()
    assert youtube.get_channel().id == A  # Explicit uploads never change the default.


def test_tokens_never_reach_settings_or_logs(accounts, caplog):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B)])
    with caplog.at_level(logging.DEBUG):
        youtube.add_account()
        youtube.add_account()
        youtube.list_accounts()
        youtube.remove_account(B)
    text = settings.path.read_text(encoding='utf-8') + caplog.text
    for secret in ('access-' + A, 'refresh-' + A, 'access-' + B, 'refresh-' + B, 'test-client-secret'):
        assert secret not in text
    assert set(settings.get('youtube_accounts')[0]) == {'id', 'title', 'thumbnail_url', 'is_default'}


def test_settings_reject_secret_or_invalid_account_fields(accounts):
    _, _, settings, _, _, _ = accounts
    with pytest.raises(ValueError):
        settings.set('youtube_accounts', [{'id': A, 'title': 'A', 'thumbnail_url': None,
            'is_default': True, 'token': 'never-persist'}])


@pytest.mark.parametrize('rejected', [False, True])
def test_listing_refreshes_only_its_token_and_handles_revocation(accounts, monkeypatch, rejected):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B)])
    youtube.add_account()
    youtube.add_account()
    expired = json.loads(secrets.get(auth.account_token_key(A)))
    expired['expiry'] = '2020-01-01T00:00:00Z'
    secrets.set(auth.account_token_key(A), json.dumps(expired))
    untouched = secrets.get(auth.account_token_key(B))
    def refresh(self, request):
        if rejected:
            raise RefreshError('invalid_grant private-provider-detail')
        self.token = 'access-' + A
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(Credentials, 'refresh', refresh)
    reopened = service.YouTubeService(secret_store=secrets, settings_store=settings)
    before = auth.authorize.call_count
    statuses = {account.id: account.status for account in reopened.list_accounts()}
    assert statuses[A] == ('expired' if rejected else 'connected')
    assert statuses[B] == 'connected'
    assert secrets.get(auth.account_token_key(B)) == untouched
    if rejected:
        assert secrets.get(auth.account_token_key(A)) is None
        with pytest.raises(AuthExpired): reopened.get_channel()
    else:
        assert json.loads(secrets.get(auth.account_token_key(A)))['refresh_token'] == 'refresh-' + A
    assert auth.authorize.call_count == before


def test_network_failure_during_refresh_retains_token_and_lists_other_account(accounts, monkeypatch):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B)])
    youtube.add_account()
    youtube.add_account()
    expired = json.loads(secrets.get(auth.account_token_key(A)))
    expired['expiry'] = '2020-01-01T00:00:00Z'
    secrets.set(auth.account_token_key(A), json.dumps(expired))
    def unavailable(self, request):
        raise TransportError('private diagnostic')
    monkeypatch.setattr(Credentials, 'refresh', unavailable)
    reopened = service.YouTubeService(secret_store=secrets, settings_store=settings)
    result = {account.id: account.status for account in reopened.list_accounts()}
    assert result == {A: 'error', B: 'connected'}
    assert secrets.get(auth.account_token_key(A)) is not None


def test_changed_authorized_channel_uses_actual_identity_and_logs_warning(accounts, caplog):
    youtube, secrets, settings, authorized, clients, _ = accounts
    authorized.append(credentials(A))
    youtube.add_account()
    clients[A][0].channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': B, 'snippet': {'title': 'Actual Brand Channel'}}]}
    with caplog.at_level(logging.WARNING):
        assert youtube.get_channel().id == B
    assert 'differs from expected' in caplog.text
    assert secrets.get(auth.account_token_key(A)) is None
    assert secrets.get(auth.account_token_key(B))
    assert settings.get('youtube_accounts')[0]['title'] == 'Actual Brand Channel'


def test_disconnect_does_not_restore_default_or_remove_other_accounts(accounts):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.extend([credentials(A), credentials(B)])
    youtube.add_account()
    youtube.add_account()
    youtube.disconnect()
    reopened = service.YouTubeService(secret_store=secrets, settings_store=settings)
    with pytest.raises(AuthExpired): reopened.restore_session()
    assert {a.id: a.status for a in reopened.list_accounts()} == {A: 'expired', B: 'connected'}


def test_two_settings_instances_keep_accounts_when_ui_saves_other_preference(accounts):
    youtube, _, settings, authorized, _, _ = accounts
    ui_settings = JSONSettingsStore(settings.path)
    authorized.append(credentials(A))
    youtube.add_account()
    ui_settings.set('theme', 'dark')
    assert settings.get('theme') == 'dark'
    assert ui_settings.get('youtube_accounts')[0]['id'] == A


def test_failed_legacy_migration_keeps_original_token_for_next_start(accounts, monkeypatch):
    youtube, secrets, settings, _, _, _ = accounts
    auth.save_credentials(credentials(A), secrets)
    original = secrets.get(auth.TOKEN_KEY)
    monkeypatch.setattr(settings, 'set', Mock(side_effect=OSError('write failed')))
    with pytest.raises(OSError): youtube.restore_session()
    assert secrets.get(auth.TOKEN_KEY) == original
    assert secrets.get(auth.account_token_key(A)) is None
    auth.authorize.assert_not_called()


def test_changed_channel_blocks_upload_and_logs_without_secret_data(accounts, caplog):
    from app.errors import ContentInvalid
    youtube, _, _, authorized, clients, tmp_path = accounts
    authorized.append(credentials(A))
    youtube.add_account()
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'test')
    req = UploadRequest(path, 'Title', 'Desc', [], rights_confirmed=True)
    youtube.confirm_upload(req, made_for_kids=False, channel_id=A)
    clients[A][0].channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': B, 'snippet': {'title': 'Unexpected Brand Channel'}}]}
    with caplog.at_level(logging.WARNING), pytest.raises(ContentInvalid):
        youtube.upload(req, lambda _: None, CancelToken())
    clients[A][0].videos.return_value.insert.assert_not_called()
    assert 'channel' in caplog.text.lower()
    assert 'access-' + A not in caplog.text


def test_reconnect_can_authorize_another_brand_channel_without_deleting_old_account(accounts, caplog):
    youtube, secrets, settings, authorized, _, _ = accounts
    authorized.append(credentials(A))
    youtube.add_account()
    youtube.disconnect()
    authorized.append(credentials(B))
    with caplog.at_level(logging.WARNING):
        assert youtube.connect().id == B
    assert {row['id'] for row in settings.get('youtube_accounts')} == {A, B}
    assert next(row['id'] for row in settings.get('youtube_accounts') if row['is_default']) == B
    assert 'different channel' in caplog.text
    assert secrets.get(auth.account_token_key(A)) is None
    assert secrets.get(auth.account_token_key(B))
