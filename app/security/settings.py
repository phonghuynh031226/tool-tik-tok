"""Nonsecret UTF-8 settings with explicit handling of external download paths."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any

from app.core.paths import safe_path
from .paths import PathConfirmationRequired, assess_download_directory
from .redaction import nonsecret_value

_ALIASES = {'privacy': 'default_privacy', 'language': 'ui_language', 'prompt': 'custom_prompt', 'download_directory': 'download_dir'}


class JSONSettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = safe_path(path if path is not None else Path('config/settings.json'))
        self._lock = RLock()
        self._defaults = {'download_dir': str(safe_path('downloads')), 'theme': 'system',
                          'ui_language': 'vi', 'default_privacy': 'private', 'custom_prompt': ''}
        self._values = self._load()

    def _validate(self, key: str, value: Any) -> Any:
        if key not in self._defaults:
            raise ValueError('Chỉ được lưu các tùy chọn không nhạy cảm đã định nghĩa.')
        if key == 'download_dir':
            nonsecret_value(str(value), reject_text=True)
            return str(assess_download_directory(value).path)
        value = nonsecret_value(value, reject_text=True)
        if not isinstance(value, str):
            raise ValueError('Giá trị cấu hình phải là chuỗi.')
        if key == 'theme' and value not in {'system', 'light', 'dark'}:
            raise ValueError('Theme không hợp lệ.')
        if key == 'default_privacy' and value not in {'private', 'unlisted', 'public'}:
            raise ValueError('Quyền riêng tư mặc định không hợp lệ.')
        if key == 'ui_language' and not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', value):
            raise ValueError('Ngôn ngữ giao diện không hợp lệ.')
        return value

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            parsed = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(parsed, dict):
                raise ValueError()
            return {key: self._validate(key, value) for key, value in parsed.items()}
        except (ValueError, TypeError, OSError):
            raise ValueError('Không đọc được cấu hình an toàn. File hiện tại được giữ nguyên; hãy kiểm tra settings.json.') from None

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            key = _ALIASES.get(key, key)
            return deepcopy(self._values.get(key, self._defaults.get(key, default)))

    def set(self, key: str, value: Any) -> None:
        key = _ALIASES.get(key, key)
        if key == 'download_dir':
            self.set_download_directory(value)
            return
        with self._lock:
            validated = self._validate(key, value)
            self._save(self._values | {key: validated})

    def inspect_download_directory(self):
        return assess_download_directory(self.get('download_dir'))

    def set_download_directory(self, value: str | Path, *, user_confirmed: bool = False) -> None:
        nonsecret_value(str(value), reject_text=True)
        assessment = assess_download_directory(value)
        if assessment.requires_user_confirmation and user_confirmed is not True:
            raise PathConfirmationRequired(assessment)
        with self._lock:
            self._save(self._values | {'download_dir': str(assessment.path)})

    def _save(self, values: dict) -> None:
        path = safe_path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                    suffix='.tmp', dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(values, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            safe_path(temporary).replace(safe_path(path))
            self._values = deepcopy(values)
        finally:
            if temporary is not None and temporary.exists():
                safe_path(temporary).unlink()
