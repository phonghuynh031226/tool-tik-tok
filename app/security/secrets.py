"""Windows Credential Manager through keyring; no plaintext/backend fallback."""

from __future__ import annotations

import sys

from keyring.errors import PasswordDeleteError

from app.errors import AppError

SERVICE_NAME = 'TikTokYouTubeStudio'


class SecretStoreError(AppError):
    user_message = 'Không truy cập được Windows Credential Manager. Thông tin bí mật chưa được lưu; ứng dụng không dùng file thay thế.'
    retryable = False


def _secure_backend():
    # Bypass ambient keyring configuration/plugins: they may select plaintext files.
    if sys.platform != 'win32':
        raise SecretStoreError()
    try:
        from keyring.backends.Windows import WinVaultKeyring
        backend = WinVaultKeyring()
        if backend.priority <= 0:
            raise SecretStoreError()
        return backend
    except Exception:
        raise SecretStoreError() from None


class KeyringSecretStore:
    def __init__(self) -> None:
        self._backend = _secure_backend()

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key.strip() or len(key) > 200 or any(ord(char) < 32 for char in key):
            raise ValueError('Tên mục bí mật không hợp lệ.')

    def get(self, key: str) -> str | None:
        self._validate_key(key)
        try:
            result = self._backend.get_password(SERVICE_NAME, key)
            if result is not None and not isinstance(result, str):
                raise SecretStoreError()
            return result
        except Exception:
            raise SecretStoreError() from None

    def set(self, key: str, value: str) -> None:
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError('Giá trị bí mật phải là chuỗi.')
        try:
            self._backend.set_password(SERVICE_NAME, key, value)
        except Exception:
            raise SecretStoreError() from None

    def delete(self, key: str) -> None:
        self._validate_key(key)
        if self.get(key) is None:
            return
        try:
            self._backend.delete_password(SERVICE_NAME, key)
        except PasswordDeleteError:
            if self.get(key) is not None:
                raise SecretStoreError() from None
        except Exception:
            raise SecretStoreError() from None
