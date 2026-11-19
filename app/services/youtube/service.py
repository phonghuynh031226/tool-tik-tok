"""Synchronous YouTube backend. Use one instance on one worker at a time.

UI: display auth.OAUTH_SCOPE_EXPLANATION, import selected client config, connect,
show ChannelInfo, then call confirm_upload only on explicit user confirmation.
Cancellation takes effect between HTTP calls (each has a 30-second timeout).
Credentials/resumable URIs are never logged or written to ordinary files.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import socket
import ssl
from time import monotonic, sleep
from threading import RLock, local
from urllib.parse import urlsplit

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

from app.contracts import ChannelInfo, ChannelAccount, UploadRequest, UploadResult, JobStatus
from app.db.repository import SQLiteHistoryRepository
from app.db.stats_cache import SQLiteStatsCache, VideoWindow
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import AppError, AuthExpired, ContentInvalid, NetworkError, QuotaExceeded, AccountNotFound, StatsUnavailable
from app.security.secrets import KeyringSecretStore
from app.security.settings import JSONSettingsStore
from . import auth
from .accounts import AccountTokenStore, PendingTokenStore
from ._quiet import quiet_sdk
from .validators import invalid, validate_upload_request, validate_publish_at
from .stats import StatsReader

CHUNK_SIZE = 8 * 1024 * 1024
_VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
_CHANNEL_ID = re.compile(r'^UC[A-Za-z0-9_-]{22}$')
_UPLOAD_HOSTS = {'www.googleapis.com', 'youtube.googleapis.com', 'upload.youtube.com'}
_LOG = logging.getLogger(__name__)


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
    def __init__(self, owner, token, *, retry_4xx=True):
        self.owner, self.token = owner, token
        self.retries = 0
        self.refreshed = False
        self.retry_4xx = retry_4xx

    def refresh(self):
        if self.refreshed or self.owner._credentials is None:
            raise AuthExpired()
        self.refreshed = True
        try:
            refreshed = auth.refresh_credentials(self.owner._credentials, self.owner._secrets)
            if refreshed is not None:
                self.owner._credentials = refreshed
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
                if not self.retry_4xx and 400 <= int(error.resp.status) < 500:
                    if isinstance(mapped, AuthExpired):
                        self.owner._secrets.delete(auth.TOKEN_KEY)
                        self.owner._credentials = None
                        self.owner._confirmation = None
                    raise mapped from None
            except ssl.SSLCertVerificationError:
                raise invalid('Không xác minh được kết nối TLS an toàn với Google.') from None
            except (OSError, httplib2.HttpLib2Error, RequestsConnectionError, Timeout):
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
        self._http_local = local()
        self.token = CancelToken()
        self.on_location = None

    @property
    def raw(self):
        """A fresh socket client per request, never transferred between threads.

        httplib2's socket timeout covers both connect and read. The logical SDK
        adapter can be reused under the facade lock; its HTTP sockets cannot.
        """
        if not hasattr(self._http_local, 'raw'):
            http = httplib2.Http(timeout=30)
            http.follow_redirects = False
            http.redirect_codes = http.redirect_codes - {308}
            self._http_local.raw = http
        return self._http_local.raw

    def request(self, uri, method='GET', body=None, headers=None, **kwargs):
        self.token.raise_if_cancelled()
        parsed = urlsplit(uri)
        if parsed.scheme != 'https' or parsed.hostname not in _UPLOAD_HOSTS:
            raise invalid('Endpoint YouTube không hợp lệ.')
        if self.owner._credentials is None:
            raise AuthExpired()
        headers = dict(headers or {})
        credentials = self.owner._credentials
        with auth.credential_lock(credentials):
            credentials.apply(headers)
        # No implicit redirects carrying Authorization to another host.
        kwargs.pop('redirections', None)
        http = self.raw
        try:
            response, content = http.request(uri, method=method, body=body,
                                             headers=headers, redirections=0, **kwargs)
        finally:
            try:
                http.close()
            finally:
                del self._http_local.raw
        location = response.get('location')
        if self.on_location and location and int(response.status) in (200, 201, 308):
            self.on_location(_session_uri(location))  # Persist BEFORE SDK sends media.
        return response, content


class _YouTubeSession:
    def __init__(self, *, secret_store=None):
        self._secrets = secret_store if secret_store is not None else KeyringSecretStore()
        self._credentials = None
        self._api = None
        self._transport = None
        self._confirmation = None
        self._on_upload_accepted = None
        self._verified_channel = None

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
        self._verified_channel = None
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
        self.thumbnail_url = items[0].get('snippet', {}).get('thumbnails', {}).get('default', {}).get('url')
        self._verified_channel = ChannelInfo(items[0]['id'], str(items[0].get('snippet', {}).get('title', '')))
        return self._verified_channel

    def get_channel(self) -> ChannelInfo:
        return self._channel(_Policy(self, CancelToken()))

    def _validate_v2_request(self, req):
        if req.channel_id is not None and self.get_channel().id != req.channel_id:
            _LOG.warning('YouTube authorized channel differs from requested upload channel; upload blocked.')
            raise AccountNotFound()

    @staticmethod
    def _metadata_key(req):
        payload = asdict(req)
        # Keep existing resumable-session identities for legacy/default requests.
        for name in ('publish_at', 'channel_id'):
            if payload.get(name) is None:
                payload.pop(name, None)
        if req.publish_at is not None:
            payload['publish_at'] = req.publish_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            payload['privacy'] = 'private'
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
            _LOG.warning('YouTube authorized channel differs from confirmed upload channel; upload blocked.')
            self._confirmation = None
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
            status = JobStatus.SCHEDULED if req.publish_at is not None else JobStatus.UPLOADED
            result = UploadResult(video_id, f'https://www.youtube.com/watch?v={video_id}', channel.id, status)
            if self._on_upload_accepted is not None:
                self._on_upload_accepted(result)
            cancel_token.raise_if_cancelled()
            on_progress(1.0)
            return result

        on_progress(0.0)
        cancel_token.raise_if_cancelled()
        if state.get('video_id'):
            return finish({'id': state['video_id']})
        media = MediaFileUpload(str(path), mimetype='video/mp4', chunksize=CHUNK_SIZE, resumable=True)
        request = None
        self._transport.on_location = save_location
        try:
            # Hashing a large file may take time; recheck before sending metadata.
            validate_publish_at(req.publish_at)
            status_body = {'privacyStatus': req.privacy, 'selfDeclaredMadeForKids': req.made_for_kids}
            if req.publish_at is not None:
                status_body.update(privacyStatus='private',
                    publishAt=req.publish_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'))
            request = self._api.videos().insert(part='snippet,status', body={
                'snippet': {'title': req.title, 'description': req.description, 'tags': list(req.tags),
                            'categoryId': req.category_id, 'defaultLanguage': req.default_language},
                'status': status_body}, media_body=media)
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


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class YouTubeService:
    """Synchronous multi-account backend; call from a worker, including list_accounts.

    Listing/restoring never starts OAuth. Network/refresh work is serialized against
    uploads; every account has its own transport and upload confirmation.
    """
    def __init__(self, *, secret_store=None, settings_store=None, stats_cache=None, history_repository=None):
        self._secrets = secret_store if secret_store is not None else KeyringSecretStore()
        self._settings = settings_store if settings_store is not None else JSONSettingsStore()
        self._sessions = {}
        self._lock = RLock()
        self._stats_cache = stats_cache  # Lazy default avoids opening SQLite on startup.
        self._history_repository = history_repository

    def _rows(self):
        return self._settings.get('youtube_accounts', [])

    def _default_id(self):
        return next((row['id'] for row in self._rows() if row['is_default']), None)

    @property
    def _transport(self):
        session = self._sessions.get(self._default_id())
        return session._transport if session else None

    _metadata_key = staticmethod(_YouTubeSession._metadata_key)

    def _register(self, session, channel, previous_id=None):
        rows = self._rows()
        previous = next((row for row in rows if row['id'] == (previous_id or channel.id)), None)
        existing = next((row for row in rows if row['id'] == channel.id), None)
        row = {'id': channel.id, 'title': channel.title,
               'thumbnail_url': getattr(session, 'thumbnail_url', None),
               'is_default': bool((existing or previous or {}).get('is_default', not rows))}
        rows = [item for item in rows if item['id'] not in {previous_id, channel.id}]
        rows.append(row)
        if row['is_default']:
            for item in rows:
                item['is_default'] = item['id'] == channel.id
        elif not any(item['is_default'] for item in rows):
            rows[0]['is_default'] = True
        scoped = AccountTokenStore(self._secrets, channel.id)
        # Persist token before metadata; retain the legacy/source token on failure.
        saved = scoped.get(auth.TOKEN_KEY)
        token = session._secrets.get(auth.TOKEN_KEY)
        if not token:
            token = session._credentials.to_json()
        scoped.set(auth.TOKEN_KEY, token)
        try:
            self._settings.set('youtube_accounts', rows)
        except BaseException:
            if saved is None:
                scoped.delete(auth.TOKEN_KEY)
            else:
                scoped.set(auth.TOKEN_KEY, saved)
            raise
        session._secrets = scoped
        self._sessions[channel.id] = session
        if previous_id and previous_id != channel.id:
            self._secrets.delete(auth.account_token_key(previous_id))
            self._sessions.pop(previous_id, None)
        return ChannelAccount(**next(item for item in rows if item['id'] == channel.id))

    def _verify_identity(self, session, channel, expected, *, strict=False):
        if channel.id != expected:
            _LOG.warning('YouTube authorized channel differs from expected channel; account identity updated; upload requires confirmation again.')
            session._confirmation = None
            self._register(session, channel, previous_id=expected)
            if strict:
                raise invalid('Kênh được Google cấp quyền khác kênh đã chọn. Hãy kiểm tra và xác nhận lại kênh đích.')
        return channel

    def _session_for(self, channel_id=None, *, reload=False, strict=False):
        channel_id = channel_id or self._default_id()
        if channel_id is None:
            raise AuthExpired()
        if channel_id not in {row['id'] for row in self._rows()}:
            raise AccountNotFound()
        store = AccountTokenStore(self._secrets, channel_id)
        if not store.get(auth.TOKEN_KEY):
            self._sessions.pop(channel_id, None)
            raise auth.session_expired()
        session = self._sessions.get(channel_id)
        if session is None:
            session = _YouTubeSession(secret_store=store)
            self._sessions[channel_id] = session
        if reload or session._credentials is None or session._api is None:
            confirmation = session._confirmation
            channel = session.restore_session()
            if channel is None:
                raise auth.session_expired()
            self._verify_identity(session, channel, channel_id, strict=strict)
            if channel.id == channel_id:
                session._confirmation = confirmation
        return session

    @_serialized
    def import_client_secret(self, selected_path):
        old = self._secrets.get(auth.CLIENT_KEY)
        auth.import_client_secret(selected_path, self._secrets)
        if old != self._secrets.get(auth.CLIENT_KEY):
            for row in self._rows():
                self._secrets.delete(auth.account_token_key(row['id']))
            for session in self._sessions.values():
                if session._transport:
                    session._transport.token.cancel()
            self._sessions.clear()

    @_serialized
    def restore_session(self):
        """Worker startup path: migrate a legacy grant, or silently load default."""
        default = self._default_id()
        if default is not None:
            session = self._session_for(default, reload=True)
            return session._verified_channel
        legacy = _YouTubeSession(secret_store=self._secrets)
        channel = legacy.restore_session()
        if channel is None:
            return None
        self._register(legacy, channel)
        self._secrets.delete(auth.TOKEN_KEY)
        _LOG.info('YouTube legacy account migrated to per-channel SecretStore.')
        return channel

    @_serialized
    def connect(self):
        default = self._default_id()
        if default is None:
            session = _YouTubeSession(secret_store=self._secrets)
        else:
            try:
                session = self._session_for(default, reload=True)
                return session._verified_channel
            except AuthExpired:
                # OAuth may grant a different Brand channel: do not overwrite
                # the old account's token before Google identifies the channel.
                session = _YouTubeSession(secret_store=PendingTokenStore(self._secrets))
        channel = session.connect()
        if default and channel.id != default:
            _LOG.warning('YouTube OAuth authorized a different channel from the previous default.')
        self._register(session, channel)
        if default is not None:
            self.set_default_account(channel.id)
        self._secrets.delete(auth.TOKEN_KEY)
        _LOG.info('YouTube channel connected.')
        return channel

    @_serialized
    def get_channel(self):
        default = self._default_id()
        session = self._session_for(default)
        return self._verify_identity(session, session.get_channel(), default)

    @_serialized
    def disconnect(self):
        default = self._default_id()
        if default is not None:
            session = self._sessions.pop(default, None)
            if session:
                session.disconnect()
            self._secrets.delete(auth.account_token_key(default))
        self._secrets.delete(auth.TOKEN_KEY)
        _LOG.info('YouTube default account disconnected.')

    @_serialized
    def list_accounts(self):
        # Contracts are synchronous; the caller runs this method in its worker.
        if not self._rows():
            try:
                self.restore_session()
            except AuthExpired:
                pass
        statuses = {}
        for row in self._rows():
            try:
                session = self._session_for(row['id'], reload=True)
                channel = session._verified_channel  # Already verified by this restore, not a second API read.
                statuses[channel.id] = 'connected'
            except AuthExpired:
                statuses[row['id']] = 'expired'
            except AppError:
                statuses[row['id']] = 'error'
        return [ChannelAccount(**row, status=statuses.get(row['id'], 'error')) for row in self._rows()]

    @_serialized
    def add_account(self):
        session = _YouTubeSession(secret_store=PendingTokenStore(self._secrets))
        channel = session.connect()
        result = self._register(session, channel)
        _LOG.info('YouTube account added or reauthorized.')
        return result

    @_serialized
    def remove_account(self, channel_id):
        rows = self._rows()
        if channel_id not in {row['id'] for row in rows}:
            raise AccountNotFound()
        self._secrets.delete(auth.account_token_key(channel_id))
        rows = [row for row in rows if row['id'] != channel_id]
        if rows and not any(row['is_default'] for row in rows):
            rows[0]['is_default'] = True
        self._settings.set('youtube_accounts', rows)
        self._sessions.pop(channel_id, None)
        # Prevent a legacy grant from resurrecting a removed/disconnected account.
        self._secrets.delete(auth.TOKEN_KEY)
        _LOG.info('YouTube account removed.')

    @_serialized
    def set_default_account(self, channel_id):
        rows = self._rows()
        if channel_id not in {row['id'] for row in rows}:
            raise AccountNotFound()
        for row in rows:
            row['is_default'] = row['id'] == channel_id
        self._settings.set('youtube_accounts', rows)
        for session in self._sessions.values():
            session._confirmation = None

    @_serialized
    def confirm_upload(self, req, *, made_for_kids, channel_id):
        validate_upload_request(req)
        session = self._session_for(req.channel_id, strict=True)
        session.confirm_upload(req, made_for_kids=made_for_kids, channel_id=channel_id)

    @_serialized
    def upload(self, req, on_progress, cancel_token):
        validate_upload_request(req)
        cancel_token.raise_if_cancelled()
        session = self._session_for(req.channel_id, strict=True)
        def accepted(result):
            if result.status == JobStatus.SCHEDULED:
                self._history().record_scheduled_upload(req, result)
                _LOG.info('YouTube upload scheduled privately; public visibility not yet confirmed.')
        session._on_upload_accepted = accepted if req.publish_at is not None else None
        try:
            return session.upload(req, on_progress, cancel_token)
        finally:
            session._on_upload_accepted = None

    def _history(self):
        if self._history_repository is None:
            self._history_repository = SQLiteHistoryRepository(secret_store=self._secrets)
        return self._history_repository

    @_serialized
    def check_processing(self, video_id):
        return self._session_for().check_processing(video_id)

    def _cache_for(self, channel_id):
        if channel_id not in {row['id'] for row in self._rows()}:
            raise AccountNotFound()
        if self._stats_cache is None:
            self._stats_cache = SQLiteStatsCache()
        return self._stats_cache

    @staticmethod
    def _fresh(stamp):
        return (stamp is not None and stamp.tzinfo is not None
                and 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() < 600)

    def _stats_reader(self, channel_id):
        # Load without channels.list: the statistics request itself verifies the
        # authorized channel, so a fresh-cache hit makes zero API calls.
        store = AccountTokenStore(self._secrets, channel_id)
        if not store.get(auth.TOKEN_KEY):
            raise auth.session_expired()
        session = self._sessions.get(channel_id)
        if session is None or session._credentials is None:
            session = _YouTubeSession(secret_store=store)
            try:
                session._credentials = auth.load_credentials(store)
            except AuthExpired:
                store.delete(auth.TOKEN_KEY)
                raise auth.session_expired() from None
            if session._credentials is None:
                raise auth.session_expired()
            session._build_api()
            self._sessions[channel_id] = session
        def verify(item):
            actual = item.get('id')
            if not isinstance(actual, str) or not _CHANNEL_ID.fullmatch(actual):
                raise StatsUnavailable()
            self._verify_identity(session, ChannelInfo(actual, item.get('snippet', {}).get('title', '')),
                                  channel_id, strict=True)
        return StatsReader(session, _Policy(session, CancelToken(), retry_4xx=False), verify)

    @_serialized
    def get_channel_stats(self, channel_id, force_refresh=False):
        """YouTube may round subscriber counts; fetched_at stays old on fallback.

        No browser is opened. Fresh cache avoids API/auth refresh; API errors
        return an existing snapshot with a warning, otherwise propagate.
        """
        cache = self._cache_for(channel_id)
        old = cache.load_channel_stats(channel_id)
        if old is not None and not force_refresh and self._fresh(old.fetched_at):
            return old
        reader = None
        try:
            reader = self._stats_reader(channel_id)
            result = reader.channel_stats(channel_id)
        except AppError:
            if old is None:
                raise
            _LOG.warning('YouTube channel refresh failed; returning stale cache with original fetched_at.')
            return old
        finally:
            if reader is not None:
                reader.log_quota()
            else:
                _LOG.info('YouTube statistics refresh: estimated_quota_units=0')
        cache.save_channel_stats(result)
        return result

    @_serialized
    def list_channel_videos(self, channel_id, limit=50, force_refresh=False):
        if type(limit) is not int or limit < 0:
            raise ValueError('limit phải là số nguyên không âm.')
        cache = self._cache_for(channel_id)
        if limit == 0:
            return []
        if isinstance(cache, SQLiteStatsCache):
            old = cache.load_video_window(channel_id)
        else:
            videos = cache.load_videos(channel_id)
            stamp = min((v.fetched_at for v in videos if v.fetched_at is not None), default=None)
            old = VideoWindow(videos, stamp, len(videos), False)
        if (not force_refresh and self._fresh(old.fetched_at)
                and (old.complete or old.requested_limit >= limit)):
            return old.videos[:limit]
        reader = None
        try:
            reader = self._stats_reader(channel_id)
            result, complete, stamp = reader.videos(channel_id, limit)
        except AppError:
            if old.fetched_at is None and not old.videos:
                raise
            _LOG.warning('YouTube video refresh failed; returning stale cache with original fetched_at.')
            return old.videos[:limit]
        finally:
            if reader is not None:
                reader.log_quota()
            else:
                _LOG.info('YouTube statistics refresh: estimated_quota_units=0')
        if isinstance(cache, SQLiteStatsCache):
            cache.save_video_window(channel_id, result, requested_limit=limit, complete=complete, fetched_at=stamp)
        else:
            cache.save_videos(channel_id, result)
        return result

    @_serialized
    def sync_scheduled(self):
        """Return only API-confirmed public videos; overdue private jobs need review.

        This method never uploads, changes privacy or infers publication from the
        clock/cache. Each channel is checked with its own token, at most 50 ids
        per request. Missing/failed/mismatched results remain SCHEDULED.
        """
        history = self._history()
        groups = {}
        for job in history.list_scheduled():
            channel = job.get('channel_id') or job.get('youtube_channel_id')
            groups.setdefault(channel, []).append(job)
        published = []
        for channel_id, jobs in groups.items():
            reader = None
            try:
                if not isinstance(channel_id, str) or not _CHANNEL_ID.fullmatch(channel_id):
                    raise AccountNotFound()
                reader = self._stats_reader(channel_id)
                for offset in range(0, len(jobs), 50):
                    batch = jobs[offset:offset + 50]
                    ids = [job.get('youtube_video_id') for job in batch]
                    if any(not isinstance(value, str) or not _VIDEO_ID.fullmatch(value) for value in ids):
                        raise invalid('Lịch hẹn thiếu mã video YouTube hợp lệ. Cần kiểm tra lại.')
                    payload = reader.request(lambda: reader.session._api.videos().list(
                        part='snippet,status,processingDetails', id=','.join(dict.fromkeys(ids))))
                    items = {item['id']: item for item in payload.get('items', [])
                             if isinstance(item, dict) and item.get('id') in ids}
                    for job in batch:
                        item = items.get(job['youtube_video_id'], {})
                        status = item.get('status', {})
                        same_channel = item.get('snippet', {}).get('channelId') == channel_id
                        failed = (status.get('uploadStatus') in {'failed', 'rejected', 'deleted'}
                                  or item.get('processingDetails', {}).get('processingStatus') in {'failed', 'terminated'})
                        now = datetime.now(timezone.utc)
                        changes = {'schedule_checked_at': now.isoformat(), 'uploaded_at': None}
                        if same_channel and status.get('privacyStatus') == 'public' and not failed:
                            changes.update(processing_status=JobStatus.UPLOADED, privacy_status='public',
                                           uploaded_at=now.isoformat(), schedule_needs_review=False,
                                           schedule_public_confirmed=True, error_message=None)
                            history.update(job['id'], changes)
                            published.append(UploadResult(job['youtube_video_id'],
                                f"https://www.youtube.com/watch?v={job['youtube_video_id']}", channel_id))
                            _LOG.info('YouTube API confirmed scheduled video is public.')
                            continue
                        try:
                            due = datetime.fromisoformat(job['scheduled_at'])
                            overdue = due <= now
                        except (TypeError, KeyError, ValueError):
                            overdue = True
                        review = overdue or not same_channel or failed or status.get('privacyStatus') not in {'private', 'public'}
                        changes.update(schedule_needs_review=review, error_message=(
                            'Cần kiểm tra: YouTube chưa xác nhận video công khai; có thể đã quá giờ hẹn, video bị hạn chế hoặc không truy cập được.'
                            if review else None))
                        history.update(job['id'], changes)
            except AppError as error:
                for job in jobs:
                    # Preserve any publication already confirmed in an earlier batch.
                    if any(result.video_id == job.get('youtube_video_id') and result.channel_id == channel_id for result in published):
                        continue
                    history.update(job['id'], {'schedule_needs_review': True,
                        'error_message': 'Cần kiểm tra lịch công khai: ' + error.user_message})
                _LOG.warning('YouTube scheduled sync could not verify publication; jobs need review.')
            finally:
                if reader is not None:
                    reader.log_quota()
        return published
