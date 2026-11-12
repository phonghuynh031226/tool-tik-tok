"""Credential redaction shared by persistence and logs; no secret values logged."""

from __future__ import annotations

import re
from typing import Any

REDACTED = '<REDACTED>'
_KEYS = r'(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|client[_-]?secret|password|authorization|cookies?|upload[_-]?session[_-]?uri)'
_COOKIE_HEADER = re.compile(r'(?P<prefix>\b(?:set-cookie|cookie)\s*:\s*)[^\r\n]+', re.IGNORECASE)
_CONTAINER = re.compile(rf'''(?P<prefix>["']?{_KEYS}["']?\s*[:=]\s*)[{{\[][^\r\n]*''', re.IGNORECASE)
_QUOTED = re.compile(rf'''(?P<prefix>["']?{_KEYS}["']?\s*[:=]\s*)(?P<quote>["'])(?P<value>.*?)(?P=quote)''', re.IGNORECASE)
_PLAIN = re.compile(rf'''(?P<prefix>\b{_KEYS}\s*[:=]\s*)(?!["'])(?:Bearer\s+)?[^\s&,;}}\]]+''', re.IGNORECASE)
_QUERY = re.compile(r'(?P<prefix>[?&](?:key|api_key|apikey|access_token|refresh_token|token|upload_id|X-Goog-Signature|X-Amz-Signature|X-Amz-Credential)=)[^&\s"\']+', re.IGNORECASE)
_BEARER = re.compile(r'\bBearer\s+(?!<REDACTED>)[A-Za-z0-9._~+/=-]+', re.IGNORECASE)
_PATTERNS = [
    re.compile(r'AIza[A-Za-z0-9_-]{20,}'),
    re.compile(r'ya29\.[A-Za-z0-9._~-]+'),
    re.compile(r'1//[A-Za-z0-9_-]{12,}'),
    re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{12,}'),
    re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),
]
_USERINFO = re.compile(r'(https?://)[^/\s@]+@', re.IGNORECASE)


def redact_text(value: str) -> str:
    text = _COOKIE_HEADER.sub(lambda match: match['prefix'] + REDACTED, value)
    # A stringified credential container may have arbitrary nested structure.
    # Drop the rest of that line rather than risk retaining a nested secret.
    text = _CONTAINER.sub(lambda match: match['prefix'] + REDACTED, text)
    text = _USERINFO.sub(lambda match: match[1] + REDACTED + '@', text)
    text = _QUOTED.sub(lambda match: match['prefix'] + match['quote'] + REDACTED + match['quote'], text)
    text = _PLAIN.sub(lambda match: match['prefix'] + REDACTED, text)
    text = _QUERY.sub(lambda match: match['prefix'] + REDACTED, text)
    text = _BEARER.sub('Bearer ' + REDACTED, text)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r'[^a-z0-9]', '', key.lower())
    return any(part in normalized for part in ('apikey', 'accesstoken', 'refreshtoken', 'idtoken',
        'clientsecret', 'password', 'authorization', 'credential', 'uploadsessionuri')) or normalized.endswith(('token', 'secret')) or normalized in {'cookie', 'cookies'}


def nonsecret_value(value: Any, *, reject_text: bool = False) -> Any:
    """Detach JSON-compatible data, reject secret field names and scrub text.

    Settings use reject_text=True to reject unsafe input rather than changing
    the user's prompt. Persistence may scrub credential text in error messages.
    """
    if isinstance(value, str):
        clean = redact_text(value)
        if reject_text and clean != value:
            raise ValueError('Không được lưu thông tin bí mật vào cấu hình hoặc dữ liệu thường.')
        return clean
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [nonsecret_value(item, reject_text=reject_text) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or is_sensitive_key(key):
                raise ValueError('Thông tin bí mật phải lưu trong SecretStore.')
            result[key] = nonsecret_value(item, reject_text=reject_text)
        return result
    raise TypeError('Chỉ hỗ trợ dữ liệu JSON không nhạy cảm.')
