"""Strict TikTok URL boundary. Only short links perform controlled HTTP requests."""

from __future__ import annotations

import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.errors import DisallowedHost, InvalidUrl
from .errors import failure, map_error

ALLOWED_HOSTS = frozenset({'tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'})
MAX_REDIRECTS = 5
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_VIDEO = re.compile(r'^/(?:(?:@(?P<author>[A-Za-z0-9_.-]+)|share)/video|embed(?:/v2)?|video)/(?P<id>[0-9]{1,32})/?$')
RedirectRequest = Callable[[str], tuple[int, str | None]]


def validate_url(url: str) -> str:
    """Validate and return HTTPS URL without query/fragment; no HTTP request."""
    if not isinstance(url, str):
        raise InvalidUrl()
    value = url.strip()
    if not value or any(ord(char) < 33 or ord(char) == 127 for char in value) or '\\' in value:
        raise InvalidUrl()
    if '://' not in value:
        if '.' not in value.split('/', 1)[0]:
            raise InvalidUrl()
        value = 'https://' + value
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise InvalidUrl() from None
    if parsed.scheme.lower() not in {'http', 'https'} or parsed.username is not None or parsed.password is not None:
        raise InvalidUrl()
    if host not in ALLOWED_HOSTS:
        raise DisallowedHost()
    if port is not None and port != (443 if parsed.scheme.lower() == 'https' else 80):
        raise InvalidUrl()
    path = unquote(parsed.path)
    if re.search(r'/photo(?:/|$)', path, re.IGNORECASE):
        raise failure(InvalidUrl, 'Liên kết /photo/ là bài ảnh (slideshow), không phải video MP4 được hỗ trợ.')
    if '%' in parsed.path or path != parsed.path or not path or any(part in ('.', '..') for part in path.split('/')):
        raise InvalidUrl()
    return urlunsplit(('https', host, path, '', ''))


def extract_video_id(url: str) -> str:
    match = _VIDEO.fullmatch(urlsplit(validate_url(url)).path)
    if not match:
        raise failure(InvalidUrl, 'Liên kết chưa chứa mã video TikTok hợp lệ. Hãy sử dụng liên kết video hoặc giải liên kết rút gọn trước.')
    return match['id']


def normalize_url(url: str) -> str:
    clean = validate_url(url)
    match = _VIDEO.fullmatch(urlsplit(clean).path)
    if not match:
        raise InvalidUrl()
    return f'https://www.tiktok.com/@{match["author"] or "_"}/video/{match["id"]}'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request_redirect(url: str) -> tuple[int, str | None]:
    # No automatic redirects or ambient proxy routing. Read headers only, not body.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(url, headers={'User-Agent': 'TikTokYouTubeStudio/1.0'}, method='GET')
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.headers.get('Location')
    except HTTPError as error:
        try:
            if error.code in REDIRECT_CODES:
                return error.code, error.headers.get('Location')
            raise map_error(error) from None
        finally:
            error.close()
    except (URLError, OSError) as error:
        raise map_error(error) from None


def resolve_url(url: str, *, request_redirect: RedirectRequest | None = None) -> str:
    """Resolve short links with <=5 redirects; validate BEFORE every request."""
    current = validate_url(url)
    parsed = urlsplit(current)
    if _VIDEO.fullmatch(parsed.path):
        return normalize_url(current)
    is_short = (parsed.hostname in {'vm.tiktok.com', 'vt.tiktok.com'} and
                re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path)) or re.fullmatch(r'/t/[A-Za-z0-9_-]+/?', parsed.path)
    if not is_short:
        raise InvalidUrl()
    request = request_redirect or _request_redirect
    visited: set[str] = set()
    redirects = 0
    while True:
        current = validate_url(current)
        if current in visited:
            raise failure(InvalidUrl, 'Liên kết TikTok bị lặp chuyển hướng.')
        visited.add(current)
        status, location = request(current)
        if status not in REDIRECT_CODES:
            if status != 200:
                raise failure(InvalidUrl, 'Không giải được liên kết rút gọn TikTok.')
            return normalize_url(current)
        if redirects >= MAX_REDIRECTS:
            raise failure(InvalidUrl, 'Liên kết TikTok vượt quá giới hạn 5 lần chuyển hướng.')
        if not location or not location.strip() or location != location.strip():
            raise InvalidUrl()
        current = validate_url(urljoin(current, location))
        redirects += 1
