"""Synchronous YouTube backend. Use one instance on one worker at a time.

UI: display auth.OAUTH_SCOPE_EXPLANATION, import selected client config, connect,
show ChannelInfo, then call confirm_upload only on explicit user confirmation.
Cancellation takes effect between HTTP calls (each has a 30-second timeout).
Credentials/resumable URIs are never logged or written to ordinary files.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import ssl
from time import monotonic, sleep
from urllib.parse import urlsplit

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

from app.contracts import ChannelInfo, ChannelAccount, UploadRequest, UploadResult
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import AppError, AuthExpired, ContentInvalid, NetworkError, QuotaExceeded, AccountNotFound, StatsUnavailable
from app.security.secrets import KeyringSecretStore
from . import auth
from ._quiet import quiet_sdk
from .validators import invalid, validate_upload_request

CHUNK_SIZE = 8 * 1024 * 1024
_VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
_CHANNEL_ID = re.compile(r'^UC[A-Za-z0-9_-]{22}$')
_UPLOAD_HOSTS = {'www.googleapis.com', 'youtube.googleapis.com', 'upload.youtube.com'}


def _session_uri(value):
    if not isinstance(value, str) or any(ord(char) < 33 for char in value):
        raise invalid('URI phiên upload không hợp lệ.')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.hostname not in _UPLOAD_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
        raise invalid('URI phiên upload không thuộc endpoint Google được phép.')
    return value


def wait_backoff(delay, token):
    deadline = monotonic() + delay
    while True:
        token.raise_if_cancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(0.05, remaining))


def _http_error(error):
    try:
        payload = json.loads(error.content)
        reasons = {item.get('reason') for item in payload.get('error', {}).get('errors', [])}
    except (ValueError, TypeError, AttributeError):
        reasons = set()
    status = int(error.resp.status)
    if reasons & {'quotaExceeded', 'dailyLimitExceeded', 'dailyLimitExceededUnreg'}:
        return QuotaExceeded()
    if status == 401:
        return AuthExpired()
    if status in (408, 429) or 500 <= status <= 599:
        return NetworkError()
    if status in (404, 410):
        return invalid('Video hoặc phiên upload không còn tồn tại. Không tự tạo upload mới; hãy kiểm tra và xác nhận lại.')
    return invalid('YouTube từ chối yêu cầu. Hãy kiểm tra nội dung và quyền truy cập tài khoản.')


class _Policy:
    def __init__(self, owner, token):
        self.owner, self.token = owner, token
        self.retries = 0
        self.refreshed = False

    def refresh(self):
        if self.refreshed or self.owner._credentials is None:
            raise AuthExpired()
        self.refreshed = True
        try:
            auth.refresh_credentials(self.owner._credentials, self.owner._secrets)
        except AuthExpired:
            self.owner._secrets.delete(auth.TOKEN_KEY)
            self.owner._credentials = None
            self.owner._confirmation = None
            raise

    def call(self, operation):
        while True:
            self.token.raise_if_cancelled()
            credentials = self.owner._credentials
            if credentials is None:
                raise AuthExpired()
            if credentials.expired or not credentials.valid:
                self.refresh()
            try:
                with quiet_sdk():
                    result = operation()
                return result
            except HttpError as error:
                mapped = _http_error(error)
            except ssl.SSLError:
                raise invalid('Không xác minh được kết nối TLS an toàn với Google.') from None
            except (ConnectionError, TimeoutError, socket.gaierror, httplib2.HttpLib2Error, RequestsConnectionError, Timeout):
                mapped = NetworkError()
            self.token.raise_if_cancelled()
            if isinstance(mapped, AuthExpired):
                self.refresh()
            elif isinstance(mapped, NetworkError) and self.retries < 5:
                wait_backoff(2 ** self.retries, self.token)
                self.retries += 1
            else:
                raise mapped from None


class _Transport:
    def __init__(self, owner):
        self.owner = owner
        self.raw = httplib2.Http(timeout=30)
        self.raw.follow_redirects = False
        self.raw.redirect_codes = self.raw.redirect_codes - {308}
        self.token = CancelToken()
        self.on_location = None

    def request(self, uri, method='GET', body=None, headers=None, **kwargs):
        self.token.raise_if_cancelled()
        parsed = urlsplit(uri)
        if parsed.scheme != 'https' or parsed.hostname not in _UPLOAD_HOSTS:
            raise invalid('Endpoint YouTube không hợp lệ.')
        if self.owner._credentials is None:
            raise AuthExpired()
        headers = dict(headers or {})
        self.owner._credentials.apply(headers)
        # No implicit redirects carrying Authorization to another host.
        kwargs.pop('redirections', None)
        response, content = self.raw.request(uri, method=method, body=body,
                                             headers=headers, redirections=0, **kwargs)
        location = response.get('location')
        if self.on_location and location and int(response.status) in (200, 201, 308):
            self.on_location(_session_uri(location))  # Persist BEFORE SDK sends media.
        return response, content


class YouTubeService:
    def __init__(self, *, secret_store=None):
        self._secrets = secret_store if secret_store is not None else KeyringSecretStore()
        self._credentials = None
        self._api = None
        self._transport = None
        self._confirmation = None

    def import_client_secret(self, selected_path: Path) -> None:
        auth.import_client_secret(selected_path, self._secrets)
        if self._transport:
            self._transport.token.cancel()
        self._credentials = None
        self._api = None
        self._confirmation = None

    def connect(self) -> ChannelInfo:
        self._confirmation = None
        try:
            self._credentials = auth.load_credentials(self._secrets)
        except AuthExpired:
            self._secrets.delete(auth.TOKEN_KEY)
            self._credentials = None
        if self._credentials is None:
            self._credentials = auth.authorize(self._secrets)
        self._build_api()
        return self.get_channel()

    def _build_api(self):
        self._transport = _Transport(self)
        with quiet_sdk():
            self._api = build('youtube', 'v3', http=self._transport, cache_discovery=False, static_discovery=True)

    def restore_session(self) -> ChannelInfo | None:
        """Silent startup path: NEVER authorize or open a browser.

        Invalid credentials are removed, but the imported Desktop client stays
        in SecretStore. Network failures retain credentials for a later retry.
        """
        self._confirmation = None
        try:
            self._credentials = auth.load_credentials(self._secrets)
            self._api = None
            if self._credentials is None:
                return None
            self._build_api()
            return self.get_channel()  # _Policy performs at most one refresh.
        except AuthExpired:
            self._credentials = None
            self._api = None
            self._secrets.delete(auth.TOKEN_KEY)
            raise auth.session_expired() from None

    def disconnect(self) -> None:
        if self._transport:
            self._transport.token.cancel()
        self._credentials = None
        self._api = None
        self._confirmation = None
        self._secrets.delete(auth.TOKEN_KEY)

    def _connected(self):
        if self._api is None or self._credentials is None:
            raise AuthExpired()

    def _channel(self, policy) -> ChannelInfo:
        self._connected()
        payload = policy.call(lambda: self._api.channels().list(part='snippet', mine=True).execute(num_retries=0))
        items = payload.get('items', []) if isinstance(payload, dict) else []
        if len(items) != 1 or not _CHANNEL_ID.fullmatch(str(items[0].get('id', ''))):
            raise invalid('Không xác định được một kênh YouTube đích hợp lệ cho tài khoản.')
        return ChannelInfo(items[0]['id'], str(items[0].get('snippet', {}).get('title', '')))

    def get_channel(self) -> ChannelInfo:
        return self._channel(_Policy(self, CancelToken()))

    # V2 protocol adapters retain the current single-account production backend.
    # Full multi-account/statistics/scheduling implementation is a later stage.
    def list_accounts(self):
        if self._api is None or self._credentials is None:
            return []
        channel = self.get_channel()
        return [ChannelAccount(channel.id, channel.title, is_default=True)]

    def add_account(self):
        raise invalid('Thêm nhiều tài khoản thật chưa được triển khai trong bước chuẩn bị v2.')

    def remove_account(self, channel_id):
        self.set_default_account(channel_id)
        self.disconnect()

    def set_default_account(self, channel_id):
        if self.get_channel().id != channel_id:
            raise AccountNotFound()

    def get_channel_stats(self, channel_id, force_refresh=False):
        raise StatsUnavailable()

    def list_channel_videos(self, channel_id, limit=50, force_refresh=False):
        raise StatsUnavailable()

    def sync_scheduled(self):
        return []

    def _validate_v2_request(self, req):
        if req.publish_at is not None:
            raise invalid('Hẹn giờ đăng thật chưa được triển khai trong bước chuẩn bị v2.')
        if req.channel_id is not None and self.get_channel().id != req.channel_id:
            raise AccountNotFound()

    @staticmethod
    def _metadata_key(req):
        payload = asdict(req)
        # Keep existing resumable-session identities for legacy/default requests.
        for name in ('publish_at', 'channel_id'):
            if payload.get(name) is None:
                payload.pop(name, None)
        payload['path'] = str(safe_path(req.path))
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def confirm_upload(self, req: UploadRequest, *, made_for_kids: bool, channel_id: str) -> None:
        validate_upload_request(req)
        self._validate_v2_request(req)
        if not isinstance(made_for_kids, bool) or made_for_kids != req.made_for_kids:
            raise invalid('Lựa chọn đối tượng trẻ em phải được truyền rõ và khớp yêu cầu upload.')
        channel = self.get_channel()
        if channel.id != channel_id:
            raise invalid('Kênh đích không khớp kênh người dùng xác nhận.')
        self._confirmation = (self._metadata_key(req), channel_id)

    def upload(self, req, on_progress, cancel_token):
        transport = self._transport
        try:
            return self._upload(req, on_progress, cancel_token)
        finally:
            if transport is not None:
                transport.on_location = None
                transport.token = CancelToken()

    def _upload(self, req, on_progress, cancel_token):
        validate_upload_request(req)
        cancel_token.raise_if_cancelled()
        self._validate_v2_request(req)
        self._connected()
        metadata_key = self._metadata_key(req)
        if not self._confirmation or self._confirmation[0] != metadata_key:
            raise invalid('Hãy xem nội dung, chọn rõ đối tượng trẻ em và xác nhận kênh trước khi upload.')
        self._transport.token = cancel_token
        policy = _Policy(self, cancel_token)
        channel = self._channel(policy)
        if channel.id != self._confirmation[1]:
            raise invalid('Kênh YouTube đã thay đổi; cần xác nhận lại.')
        path = safe_path(req.path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise invalid('Tệp MP4 không tồn tại hoặc rỗng.')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while chunk := source.read(1024 * 1024):
                cancel_token.raise_if_cancelled()
                digest.update(chunk)
        identity = hashlib.sha256((metadata_key + channel.id + digest.hexdigest()).encode()).hexdigest()
        key = 'youtube.session.' + identity
        state = {'identity': identity, 'uri': None, 'video_id': None}
        stored = self._secrets.get(key)
        if stored:
            try:
                state = json.loads(stored)
                if state['identity'] != identity:
                    raise ValueError()
                if state.get('uri'):
                    _session_uri(state['uri'])
            except (ValueError, TypeError, KeyError):
                raise invalid('Trạng thái phiên upload không hợp lệ; không tự tạo upload mới.') from None

        def save_location(uri):
            state['uri'] = _session_uri(uri)
            self._secrets.set(key, json.dumps(state))

        def finish(response):
            video_id = response.get('id') if isinstance(response, dict) else None
            if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
                raise invalid('YouTube chưa trả mã video hợp lệ; chưa thể báo upload thành công.')
            returned_channel = response.get('snippet', {}).get('channelId')
            if returned_channel and returned_channel != channel.id:
                raise invalid('YouTube trả về kênh khác kênh đã xác nhận.')
            state['video_id'] = video_id
            self._secrets.set(key, json.dumps(state))
            cancel_token.raise_if_cancelled()
            on_progress(1.0)
            return UploadResult(video_id, f'https://www.youtube.com/watch?v={video_id}', channel.id)

        on_progress(0.0)
        cancel_token.raise_if_cancelled()
        if state.get('video_id'):
            return finish({'id': state['video_id']})
        media = MediaFileUpload(str(path), mimetype='video/mp4', chunksize=CHUNK_SIZE, resumable=True)
        request = None
        self._transport.on_location = save_location
        try:
            request = self._api.videos().insert(part='snippet,status', body={
                'snippet': {'title': req.title, 'description': req.description, 'tags': list(req.tags),
                            'categoryId': req.category_id, 'defaultLanguage': req.default_language},
                'status': {'privacyStatus': req.privacy, 'selfDeclaredMadeForKids': req.made_for_kids}}, media_body=media)
            if state.get('uri'):
                request.resumable_uri = state['uri']
                request.resumable_progress = 0
                request._in_error_state = True  # Query server offset before sending bytes.

            def next_chunk():
                cancel_token.raise_if_cancelled()
                try:
                    return request.next_chunk(num_retries=0)
                except (HttpError, OSError, httplib2.HttpLib2Error):
                    request._in_error_state = True
                    raise
                finally:
                    if request.resumable_uri:
                        save_location(request.resumable_uri)

            while True:
                status, response = policy.call(next_chunk)
                if response is not None:
                    return finish(response)
                cancel_token.raise_if_cancelled()
                if status is not None:
                    fraction = status.progress()
                    if not isinstance(fraction, (int, float)) or not math.isfinite(fraction):
                        raise invalid('Tiến độ upload không hợp lệ.')
                    on_progress(max(0.0, min(float(fraction), 0.999)))
                cancel_token.raise_if_cancelled()
        finally:
            self._transport.on_location = None
            self._transport.token = CancelToken()
            media.stream().close()

    def check_processing(self, video_id: str) -> str:
        self._connected()
        if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
            raise invalid('Mã video YouTube không hợp lệ.')
        payload = _Policy(self, CancelToken()).call(lambda: self._api.videos().list(
            part='status,processingDetails', id=video_id).execute(num_retries=0))
        items = payload.get('items', []) if isinstance(payload, dict) else []
        if len(items) != 1 or items[0].get('id') != video_id:
            raise invalid('YouTube chưa trả về video phù hợp; chưa thể báo thành công.')
        item = items[0]
        processing = item.get('processingDetails', {}).get('processingStatus')
        upload = item.get('status', {}).get('uploadStatus')
        if upload in {'failed', 'rejected'}:
            return 'failed'
        if upload == 'deleted':
            return 'terminated'
        if processing in {'processing', 'succeeded', 'failed', 'terminated'}:
            return processing
        if upload == 'processed':
            return 'succeeded'
        return 'processing'
