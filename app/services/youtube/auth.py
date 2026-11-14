"""Desktop OAuth, PKCE and SecretStore-only credentials. No file copies/tokens."""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from requests.exceptions import ConnectionError, Timeout

from app.errors import AuthExpired
from ._quiet import quiet_sdk
from .validators import invalid

SCOPES = ('https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly')
CLIENT_KEY = 'youtube.oauth.client'
TOKEN_KEY = 'youtube.oauth.tokens'
OAUTH_SCOPE_EXPLANATION = (
    'youtube.upload: cho phép upload video bạn đã xem và xác nhận. '
    'youtube.readonly: đọc tên/mã kênh đích để bạn xác nhận và kiểm tra trạng thái xử lý video. '
    'Ứng dụng không tự đăng video khi bạn chưa xác nhận.'
)


def oauth_error(error):
    """Classify without ever exposing provider diagnostics/credentials to UI."""
    code = str(getattr(error, 'error', '')).lower()
    detail = str(error).lower()
    if any(word in detail for word in ('test user', 'testing', 'developer-approved')):
        message = 'Email chưa được thêm vào Test users. Hãy thêm email trong Google Auth Platform → Audience rồi kết nối lại.'
    elif code == 'access_denied':
        message = 'Bạn đã từ chối hoặc hủy đăng nhập Google (access_denied). Nếu Google báo ứng dụng Testing, hãy thêm email vào Test users.'
    elif code in {'invalid_client', 'unauthorized_client'}:
        message = 'OAuth client không hợp lệ. Hãy chọn client_secret.json loại Desktop từ đúng project Google.'
    elif code == 'timeout' or isinstance(error, TimeoutError) or 'timeout' in type(error).__name__.lower():
        message = 'Đã hết thời gian chờ đăng nhập Google hoặc cửa sổ đã đóng. Hãy kết nối lại; kiểm tra Test users nếu Google hiển thị lỗi 403.'
    elif code == 'network' or isinstance(error, (ConnectionError, Timeout, OSError)):
        message = 'Không kết nối được mạng tới Google. Hãy kiểm tra Internet và thử lại.'
    else:
        message = 'Không hoàn tất được xác thực Google. Hãy kiểm tra OAuth Desktop client và Test users rồi kết nối lại.'
    result = AuthExpired()
    result.user_message = message
    return result


def _client_config(value):
    if not isinstance(value, dict) or set(value) != {'installed'} or not isinstance(value['installed'], dict):
        raise invalid('Hãy chọn client_secret.json loại OAuth Desktop (installed), không phải Web.')
    config = value['installed']
    if not all(isinstance(config.get(key), str) and config[key].strip() for key in ('client_id', 'client_secret')):
        raise invalid('Cấu hình OAuth Desktop thiếu client_id hoặc client_secret.')
    if config.get('auth_uri') not in {'https://accounts.google.com/o/oauth2/auth', 'https://accounts.google.com/o/oauth2/v2/auth'} or config.get('token_uri') != 'https://oauth2.googleapis.com/token':
        raise invalid('Cấu hình OAuth phải dùng endpoint Google chính thức.')
    return value


def import_client_secret(selected_path: Path, secret_store) -> None:
    # The user-selected file may be external. Read only; never copy it into repo.
    try:
        with Path(selected_path).open('r', encoding='utf-8-sig') as source:
            text = source.read(65537)
        if len(text) > 65536:
            raise ValueError()
        config = _client_config(json.loads(text))
    except (OSError, ValueError, TypeError):
        raise invalid('Không đọc được client_secret.json OAuth Desktop hợp lệ.') from None
    secret_store.set(CLIENT_KEY, json.dumps(config, ensure_ascii=False))
    secret_store.delete(TOKEN_KEY)  # Credentials from the previous client cannot be reused.


def save_credentials(credentials, secret_store) -> None:
    secret_store.set(TOKEN_KEY, credentials.to_json())


def load_credentials(secret_store):
    stored = secret_store.get(TOKEN_KEY)
    if not stored:
        return None
    try:
        info = json.loads(stored)
        if info.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError()
        scopes = info.get('scopes', [])
        if not set(SCOPES).issubset(scopes):
            raise ValueError()
        return Credentials.from_authorized_user_info(info, scopes=SCOPES)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AuthExpired() from None


def authorize(secret_store):
    stored = secret_store.get(CLIENT_KEY)
    if not stored:
        raise invalid('Hãy chọn client_secret.json OAuth Desktop trước khi kết nối YouTube.')
    try:
        config = _client_config(json.loads(stored))
        with quiet_sdk():
            flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES, autogenerate_code_verifier=True)
            original_request = flow.oauth2session.request
            def bounded_request(*args, **kwargs):
                return original_request(*args, **(kwargs | {'timeout': 30}))
            flow.oauth2session.request = bounded_request
            credentials = flow.run_local_server(host='127.0.0.1', bind_addr='127.0.0.1', port=0,
                open_browser=True, timeout_seconds=180, authorization_prompt_message='',
                success_message='Đã kết nối tài khoản. Hãy quay lại ứng dụng để xác nhận kênh đích.',
                access_type='offline', prompt='consent')
    except Exception as error:
        raise oauth_error(error) from None
    save_credentials(credentials, secret_store)
    return credentials


def refresh_credentials(credentials, secret_store) -> None:
    try:
        with quiet_sdk():
            request = Request()
            credentials.refresh(lambda *args, **kwargs: request(*args, **(kwargs | {'timeout': 30})))
    except Exception:
        raise AuthExpired() from None
    save_credentials(credentials, secret_store)
