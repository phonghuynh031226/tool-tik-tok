import json
from pathlib import Path
from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.contracts import UploadRequest, YouTubeService as YouTubeProtocol
from app.core.cancel import CancelToken
from app.errors import AuthExpired, Cancelled, ContentInvalid, NetworkError, QuotaExceeded
from app.services.youtube.service import YouTubeService
from app.services.youtube import auth

CHANNEL = 'UC' + 'a' * 22
VIDEO = 'AbcDefGhI_1'
SESSION = 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=dummy-session'


class MemorySecrets:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)


def http_error(status, reason):
    return HttpError(httplib2.Response({'status': str(status)}),
                     json.dumps({'error': {'errors': [{'reason': reason}]}}).encode())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('httplib2.Http.request', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr('requests.sessions.Session.request', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr('webbrowser.get', Mock(side_effect=AssertionError('Browser forbidden')))


@pytest.fixture
def setup_service(monkeypatch, tmp_path):
    from app.services.youtube import service
    credentials = Mock(valid=True, expired=False, token='dummy-token')
    credentials.to_json.return_value = '{"token":"dummy-token"}'
    monkeypatch.setattr(auth, 'load_credentials', Mock(return_value=credentials))
    api = Mock()
    api.channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': CHANNEL, 'snippet': {'title': 'Kênh tiếng Việt'}}]}
    request = Mock(resumable_uri=None, resumable_progress=0, _in_error_state=False)
    request.next_chunk.return_value = (None, {'id': VIDEO, 'snippet': {'channelId': CHANNEL}})
    api.videos.return_value.insert.return_value = request
    monkeypatch.setattr(service, 'build', Mock(return_value=api))
    monkeypatch.setattr(service, 'wait_backoff', Mock())
    secrets = MemorySecrets()
    instance = YouTubeService(secret_store=secrets)
    instance.connect()
    path = tmp_path / 'demo.mp4'
    path.write_bytes(b'dummy-mp4')
    req = UploadRequest(path, 'Tiêu đề', 'Mô tả', ['demo'], rights_confirmed=True)
    instance.confirm_upload(req, made_for_kids=False, channel_id=CHANNEL)
    return instance, req, request, api, secrets, credentials


def test_upload_protocol_and_payload(setup_service):
    instance, req, request, api, _, _ = setup_service
    assert isinstance(instance, YouTubeProtocol)
    progress = []
    result = instance.upload(req, progress.append, CancelToken())
    assert (result.video_id, result.channel_id) == (VIDEO, CHANNEL)
    assert progress == [0.0, 1.0]
    body = api.videos.return_value.insert.call_args.kwargs['body']
    assert body['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}
    assert request.next_chunk.call_args.kwargs['num_retries'] == 0


def test_rights_and_confirmation_fail_before_insert(setup_service):
    instance, req, _, api, _, _ = setup_service
    req.rights_confirmed = False
    with pytest.raises(ContentInvalid):
        instance.upload(req, lambda value: None, CancelToken())
    api.videos.return_value.insert.assert_not_called()
    req.rights_confirmed = True
    req.title = 'Edited after confirmation'
    with pytest.raises(ContentInvalid):
        instance.upload(req, lambda value: None, CancelToken())
    api.videos.return_value.insert.assert_not_called()


def test_audience_and_channel_explicit(setup_service):
    instance, req, _, _, _, _ = setup_service
    with pytest.raises(TypeError):
        instance.confirm_upload(req, channel_id=CHANNEL)
    with pytest.raises(ContentInvalid):
        instance.confirm_upload(req, made_for_kids=False, channel_id='UCwrong')


def test_quota_does_not_retry(setup_service):
    instance, req, request, _, _, _ = setup_service
    request.next_chunk.side_effect = http_error(403, 'quotaExceeded')
    with pytest.raises(QuotaExceeded):
        instance.upload(req, lambda value: None, CancelToken())
    assert request.next_chunk.call_count == 1


def test_transient_five_retries_same_request(setup_service, monkeypatch):
    from app.services.youtube import service
    waits = Mock()
    monkeypatch.setattr(service, 'wait_backoff', waits)
    instance, req, request, api, _, _ = setup_service
    request.next_chunk.side_effect = http_error(503, 'backendError')
    with pytest.raises(NetworkError):
        instance.upload(req, lambda value: None, CancelToken())
    assert request.next_chunk.call_count == 6
    assert api.videos.return_value.insert.call_count == 1
    assert [call.args[0] for call in waits.call_args_list] == [1, 2, 4, 8, 16]


def test_token_refresh_once_after_401(setup_service):
    instance, req, request, _, secrets, credentials = setup_service
    request.next_chunk.side_effect = [http_error(401, 'authError'), (None, {'id': VIDEO})]
    assert instance.upload(req, lambda value: None, CancelToken()).video_id == VIDEO
    credentials.refresh.assert_called_once()
    assert auth.TOKEN_KEY in secrets.values


def test_repeated_401_stops_after_one_refresh(setup_service):
    instance, req, request, _, _, credentials = setup_service
    request.next_chunk.side_effect = http_error(401, 'authError')
    with pytest.raises(AuthExpired):
        instance.upload(req, lambda value: None, CancelToken())
    assert request.next_chunk.call_count == 2 and credentials.refresh.call_count == 1


def test_dns_error_retried_without_recreating_upload(setup_service):
    import socket
    instance, req, request, api, _, _ = setup_service
    request.next_chunk.side_effect = [socket.gaierror('temporary DNS failure'), (None, {'id': VIDEO})]
    assert instance.upload(req, lambda value: None, CancelToken()).video_id == VIDEO
    assert api.videos.return_value.insert.call_count == 1


def test_failed_refresh_requires_reconnect_and_clears_bad_token(setup_service):
    instance, req, request, _, secrets, credentials = setup_service
    credentials.refresh.side_effect = RuntimeError('dummy private refresh diagnostic')
    secrets.set(auth.TOKEN_KEY, 'dummy-expired')
    request.next_chunk.side_effect = http_error(401, 'authError')
    with pytest.raises(AuthExpired): instance.upload(req, lambda value: None, CancelToken())
    assert secrets.get(auth.TOKEN_KEY) is None


def test_resume_saved_uri_in_new_service(setup_service, monkeypatch):
    instance, req, request, api, secrets, _ = setup_service
    def interrupted(**kwargs):
        request.resumable_uri = SESSION
        raise http_error(403, 'quotaExceeded')
    request.next_chunk.side_effect = interrupted
    with pytest.raises(QuotaExceeded):
        instance.upload(req, lambda value: None, CancelToken())
    assert any(SESSION in value for value in secrets.values.values())
    second = YouTubeService(secret_store=secrets)
    second.connect()
    second.confirm_upload(req, made_for_kids=False, channel_id=CHANNEL)
    resumed = Mock(resumable_uri=None, resumable_progress=0, _in_error_state=False)
    def complete(**kwargs):
        assert resumed.resumable_uri == SESSION and resumed._in_error_state is True
        return None, {'id': VIDEO}
    resumed.next_chunk.side_effect = complete
    api.videos.return_value.insert.return_value = resumed
    assert second.upload(req, lambda value: None, CancelToken()).video_id == VIDEO


def test_cancel_mid_chunk_preserves_session(setup_service):
    instance, req, request, _, secrets, _ = setup_service
    token = CancelToken()
    def chunk(**kwargs):
        request.resumable_uri = SESSION
        return Mock(progress=lambda: 0.5), None
    request.next_chunk.side_effect = chunk
    def progress(value):
        if value > 0: token.cancel()
    with pytest.raises(Cancelled):
        instance.upload(req, progress, token)
    assert request.next_chunk.call_count == 1
    assert any(SESSION in value for value in secrets.values.values())


def test_success_requires_valid_api_id(setup_service):
    instance, req, request, _, _, _ = setup_service
    request.next_chunk.return_value = (None, {})
    with pytest.raises(ContentInvalid):
        instance.upload(req, lambda value: None, CancelToken())


def test_processing_checks_id_and_api_status(setup_service):
    instance, _, _, api, _, _ = setup_service
    response = api.videos.return_value.list.return_value.execute
    response.return_value = {'items': [{'id': VIDEO, 'processingDetails': {'processingStatus': 'processing'}}]}
    assert instance.check_processing(VIDEO) == 'processing'
    response.return_value['items'][0]['processingDetails']['processingStatus'] = 'succeeded'
    assert instance.check_processing(VIDEO) == 'succeeded'
    response.return_value = {'items': []}
    with pytest.raises(ContentInvalid): instance.check_processing(VIDEO)


def test_disconnect_deletes_tokens(setup_service):
    instance, _, _, _, secrets, _ = setup_service
    secrets.set(auth.TOKEN_KEY, 'dummy')
    instance.disconnect()
    assert secrets.get(auth.TOKEN_KEY) is None
    with pytest.raises(AuthExpired): instance.get_channel()


def test_transport_saves_location_before_return_and_does_not_redirect(setup_service):
    instance = setup_service[0]
    transport = instance._transport
    saved = []
    transport.on_location = saved.append
    response = httplib2.Response({'status': '200', 'location': SESSION})
    transport.raw.request = Mock(return_value=(response, b''))
    assert transport.request('https://www.googleapis.com/upload/youtube/v3/videos', 'POST')[0] is response
    assert saved == [SESSION]
    assert transport.raw.follow_redirects is False
    assert 308 not in transport.raw.redirect_codes


def test_expired_token_refreshed_once_before_request(setup_service):
    instance, req, _, _, _, credentials = setup_service
    credentials.expired = True
    credentials.refresh.side_effect = lambda request: setattr(credentials, 'expired', False)
    assert instance.upload(req, lambda value: None, CancelToken()).video_id == VIDEO
    credentials.refresh.assert_called_once()


def test_completed_session_replay_does_not_upload_again(setup_service):
    instance, req, request, api, _, _ = setup_service
    assert instance.upload(req, lambda value: None, CancelToken()).video_id == VIDEO
    assert instance.upload(req, lambda value: None, CancelToken()).video_id == VIDEO
    assert api.videos.return_value.insert.call_count == 1
    assert request.next_chunk.call_count == 1


def test_cancel_before_upload_and_callback_exception(setup_service):
    instance, req, request, api, _, _ = setup_service
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled): instance.upload(req, lambda value: None, token)
    api.videos.return_value.insert.assert_not_called()
    def callback(value):
        if value > 0: raise RuntimeError('callback failure')
    with pytest.raises(RuntimeError, match='callback failure'):
        instance.upload(req, callback, CancelToken())
    assert request.next_chunk.call_count == 1


def test_cancel_at_initial_progress_resets_transport_token(setup_service):
    instance, req, _, _, _, _ = setup_service
    token = CancelToken()
    with pytest.raises(Cancelled):
        instance.upload(req, lambda value: token.cancel(), token)
    assert not instance._transport.token.is_cancelled


def test_oauth_desktop_import_and_pkce(monkeypatch, tmp_path):
    config = {'installed': {'client_id': 'dummy.apps.googleusercontent.com', 'client_secret': 'dummy-only',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token'}}
    source = tmp_path / 'selected.json'
    source.write_text(json.dumps(config), encoding='utf-8')
    secrets = MemorySecrets()
    auth.import_client_secret(source, secrets)
    assert json.loads(secrets.get(auth.CLIENT_KEY)) == config
    flow = Mock()
    flow.run_local_server.return_value = Mock(valid=True, to_json=lambda: '{"token":"dummy"}')
    factory = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, 'from_client_config', factory)
    auth.authorize(secrets)
    assert factory.call_args.kwargs['autogenerate_code_verifier'] is True
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == 0 and kwargs['open_browser'] is True
    assert set(factory.call_args.kwargs['scopes']) == set(auth.SCOPES)
    assert 'youtube.upload' in auth.OAUTH_SCOPE_EXPLANATION and 'youtube.readonly' in auth.OAUTH_SCOPE_EXPLANATION
    assert list(tmp_path.iterdir()) == [source]
