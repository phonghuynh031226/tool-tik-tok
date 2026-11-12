import json
import logging
import logging.handlers
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.contracts import SecretStore, SettingsStore
from app.security.secrets import KeyringSecretStore, SecretStoreError
from app.security.settings import JSONSettingsStore
from app.security.paths import PathConfirmationRequired, assess_download_directory
from app.security.redaction import REDACTED, redact_text
from app.security.logging import configure_logging


@pytest.fixture
def backend(monkeypatch):
    from app.security import secrets
    values = {}
    backend = Mock()
    backend.get_password.side_effect = lambda service, key: values.get((service, key))
    backend.set_password.side_effect = lambda service, key, value: values.__setitem__((service, key), value)
    backend.delete_password.side_effect = lambda service, key: values.pop((service, key), None)
    monkeypatch.setattr(secrets, '_secure_backend', lambda: backend)
    return backend, values


def test_secret_store_keyring_only_and_missing_delete(backend, tmp_path):
    store = KeyringSecretStore()
    assert isinstance(store, SecretStore)
    assert store.get('gemini_api_key') is None
    store.delete('missing')
    store.set('gemini_api_key', 'dummy-secret')
    assert store.get('gemini_api_key') == 'dummy-secret'
    backend[0].set_password.assert_called_once_with('TikTokYouTubeStudio', 'gemini_api_key', 'dummy-secret')
    store.delete('gemini_api_key')
    assert store.get('gemini_api_key') is None
    assert not list(tmp_path.iterdir())


def test_keyring_failure_has_no_plaintext_fallback_or_secret_in_error(backend):
    backend[0].set_password.side_effect = RuntimeError('dummy-secret')
    with pytest.raises(SecretStoreError) as caught:
        KeyringSecretStore().set('key', 'dummy-secret')
    assert 'dummy-secret' not in str(caught.value) + caught.value.user_message


def test_keyring_ignores_ambient_backend_selection(monkeypatch):
    import keyring
    from keyring.backends.Windows import WinVaultKeyring
    monkeypatch.setattr(keyring, 'get_keyring', Mock(side_effect=AssertionError('Do not select ambient backend')))
    from app.security.secrets import _secure_backend
    assert isinstance(_secure_backend(), WinVaultKeyring)


def test_settings_defaults_unicode_and_reopen(tmp_path):
    path = tmp_path / 'settings.json'
    store = JSONSettingsStore(path)
    assert isinstance(store, SettingsStore)
    assert store.get('default_privacy') == 'private'
    assert store.get('missing', 'fallback') == 'fallback'
    store.set('theme', 'dark')
    store.set('custom_prompt', 'Viết tiêu đề tiếng Việt 🐈')
    assert JSONSettingsStore(path).get('custom_prompt') == 'Viết tiêu đề tiếng Việt 🐈'
    assert json.loads(path.read_text(encoding='utf-8'))['theme'] == 'dark'
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize(('key', 'value'), [('api_key', 'dummy'), ('refresh_token', 'dummy'),
    ('custom_prompt', 'api_key="dummy-secret"'), ('download_dir', 'downloads/api_key=dummy-secret'),
    ('default_privacy', 'everyone'), ('theme', 'unknown')])
def test_settings_reject_secrets_and_invalid_values_without_write(tmp_path, key, value):
    path = tmp_path / 'settings.json'
    store = JSONSettingsStore(path)
    with pytest.raises(ValueError):
        store.set(key, value)
    assert not path.exists()


def test_settings_invalid_json_never_silently_overwritten(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        JSONSettingsStore(path)
    assert path.read_text() == '{broken'


def test_external_path_returns_confirmation_flag_without_creating_anything(tmp_path):
    local = assess_download_directory(tmp_path / 'downloads')
    assert not local.requires_user_confirmation
    external = Path('C:/ExternalStudioDownloadsNeverCreated')
    assessment = assess_download_directory(external)
    assert assessment.path == external and assessment.requires_user_confirmation
    path = tmp_path / 'settings.json'
    store = JSONSettingsStore(path)
    with pytest.raises(PathConfirmationRequired):
        store.set('download_dir', external)
    assert not path.exists()
    store.set_download_directory(external, user_confirmed=True)
    assert store.inspect_download_directory().requires_user_confirmation
    assert JSONSettingsStore(path).inspect_download_directory().requires_user_confirmation
    assert store.get('download_dir') == str(external)


@pytest.mark.parametrize('text,secret', [
    ('api_key=short-dummy', 'short-dummy'),
    ('GEMINI_API_KEY="fake key with spaces"', 'fake key with spaces'),
    ('{"access_token": "dummy-access", "refresh_token": "dummy-refresh"}', 'dummy-access'),
    ('Authorization: Bearer opaque-dummy-token', 'opaque-dummy-token'),
    ('URL https://example.test/?key=dummy-query&x=1', 'dummy-query'),
    ('https://user:dummy-pass@example.test/path', 'dummy-pass'),
    ('key=' + 'AIza' + 'a' * 35, 'AIza' + 'a' * 35),
    ('prefix ya29.' + 'z' * 30, 'ya29.' + 'z' * 30),
    ('refresh 1//' + 'z' * 30, '1//' + 'z' * 30),
    ('secret sk-proj-' + 'z' * 30, 'sk-proj-' + 'z' * 30),
])
def test_regex_redaction(text, secret):
    cleaned = redact_text(text)
    assert secret not in cleaned and REDACTED in cleaned
    assert redact_text(cleaned) == cleaned


def test_redaction_preserves_normal_vietnamese_text():
    text = 'Tiếng Việt 🐈 video_id=123; tiêu đề và mô tả'
    assert redact_text(text) == text


def test_cookie_header_redacts_all_cookie_values():
    text = 'Cookie: sessionid=dummy-session; csrftoken=dummy-csrf'
    cleaned = redact_text(text)
    assert 'dummy-session' not in cleaned and 'dummy-csrf' not in cleaned


def test_redaction_handles_already_stringified_nested_credentials():
    text = "request {'cookies': {'sessionid': 'dummy-stringified-session'}}"
    assert 'dummy-stringified-session' not in redact_text(text)


def test_logger_redacts_nested_cookie_mapping_before_formatting(tmp_path):
    path = tmp_path / 'nested.log'
    logger = configure_logging(path)
    try:
        logger.info('Request %s', {'cookies': {'sessionid': 'dummy-nested-session'}})
        for handler in logger.handlers:
            handler.flush()
        assert 'dummy-nested-session' not in path.read_text(encoding='utf-8')
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_rotating_log_redacts_args_exception_and_backups(tmp_path):
    path = tmp_path / 'studio.log'
    logger = configure_logging(path, max_bytes=220, backup_count=3)
    try:
        for index in range(8):
            logger.info('Tiếng Việt %s access_token=%s', index, 'dummy-log-token')
        try:
            raise RuntimeError('client_secret="dummy-exception-secret"')
        except RuntimeError:
            logger.exception('Upload failed api_key=%s', 'dummy-api-key')
        for handler in logger.handlers:
            handler.flush()
        assert any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in logger.handlers)
        assert path.with_name('studio.log.1').exists()
        text = ''.join(file.read_text(encoding='utf-8') for file in tmp_path.glob('studio.log*'))
        assert all(secret not in text for secret in ['dummy-log-token', 'dummy-exception-secret', 'dummy-api-key'])
        assert REDACTED in text and 'Tiếng Việt' in text
        assert not logger.propagate
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
