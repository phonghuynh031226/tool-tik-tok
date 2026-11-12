"""Safe yt-dlp/network error translation. Raw SDK messages never reach UI/logs."""

from __future__ import annotations

import errno
import re
import ssl
from urllib.error import HTTPError

from yt_dlp.networking.exceptions import CertificateVerifyError, HTTPError as YtdlpHTTPError, TransportError
from yt_dlp.utils import GeoRestrictedError

from app.errors import AppError, DownloadFailed, NetworkError


def failure(kind: type[AppError], message: str, *, retryable: bool = False) -> AppError:
    error = kind()
    error.user_message = message
    error.retryable = retryable
    return error


def map_error(error: Exception) -> AppError:
    if isinstance(error, AppError):
        return error
    chain: list[BaseException] = []
    pending = [error]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        for cause in (getattr(item, 'cause', None), getattr(item, 'reason', None), item.__cause__, item.__context__):
            if isinstance(cause, BaseException):
                pending.append(cause)
        info = getattr(item, 'exc_info', None)
        if info and isinstance(info[1], BaseException):
            pending.append(info[1])
    text = ' '.join(str(item) for item in chain).lower()
    permanent = [
        (('private', 'friends-only', 'friends only'), 'Video riêng tư hoặc chỉ dành cho bạn bè; không thể tải.'),
        (('age-restrict', 'age restrict', 'confirm your age', 'not be comfortable for some audiences'), 'Video bị giới hạn độ tuổi; không thể tải bằng phiên hiện tại.'),
        (('not available in your country', 'not available in your region', 'geo-restrict', 'geographic restriction'), 'Video bị giới hạn khu vực; ứng dụng không vượt giới hạn này.'),
        (('deleted', 'removed', 'no longer available', 'video not found', 'does not exist'), 'Video đã bị xóa hoặc không còn tồn tại.'),
        (('drm', 'encrypted media'), 'Video được bảo vệ DRM; ứng dụng không hỗ trợ vượt DRM.'),
        (('login required', 'log in', 'login for access', 'sign in', 'requiring login'), 'TikTok yêu cầu đăng nhập; không thể tải bằng phiên hiện tại.'),
    ]
    if any(isinstance(item, GeoRestrictedError) for item in chain):
        return failure(DownloadFailed, 'Video bị giới hạn khu vực; ứng dụng không vượt giới hạn này.')
    for phrases, message in permanent:
        if any(phrase in text for phrase in phrases):
            return failure(DownloadFailed, message)
    codes = [item.code if isinstance(item, HTTPError) else item.status
             for item in chain if isinstance(item, (HTTPError, YtdlpHTTPError))]
    codes += [int(value) for value in re.findall(r'(?:http error|http status|status code)[: ]+(\d{3})', text)]
    if any(code in (404, 410) for code in codes):
        return failure(DownloadFailed, 'Video đã bị xóa hoặc không còn tồn tại.')
    if any(code in (401, 403, 451) for code in codes):
        return failure(DownloadFailed, 'TikTok từ chối truy cập video; có thể cần đăng nhập hoặc bị giới hạn quyền/khu vực.')
    if any(isinstance(item, (ssl.SSLCertVerificationError, CertificateVerifyError)) for item in chain):
        return failure(DownloadFailed, 'Không xác minh được chứng chỉ TLS của TikTok. Vui lòng kiểm tra kết nối an toàn.')
    if codes:
        if any(code in (408, 425, 429, 500, 502, 503, 504) for code in codes):
            return failure(NetworkError, 'Kết nối TikTok tạm thời bị lỗi hoặc giới hạn tần suất. Vui lòng thử lại.', retryable=True)
        return failure(DownloadFailed, 'TikTok trả về lỗi truy cập video. Vui lòng kiểm tra liên kết.')
    temporary_errno = {errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED}
    is_network = any(isinstance(item, (TimeoutError, ConnectionError, TransportError))
                     or isinstance(item, OSError) and item.errno in temporary_errno for item in chain)
    temporary_text = ('timed out', 'timeout', 'connection reset', 'connection aborted',
                      'connection refused', 'temporary failure in name resolution',
                      'name or service not known', 'getaddrinfo failed', 'remote end closed',
                      'network is unreachable', 'incomplete read')
    if is_network or any(phrase in text for phrase in temporary_text):
        return failure(NetworkError, 'Kết nối TikTok tạm thời bị gián đoạn. Vui lòng thử lại.', retryable=True)
    if any(isinstance(item, OSError) for item in chain):
        return failure(DownloadFailed, 'Không thể đọc hoặc ghi tệp trong thư mục dự án. Hãy kiểm tra quyền và dung lượng ổ đĩa.')
    return failure(DownloadFailed, 'Không lấy được video từ TikTok. Hãy kiểm tra liên kết và phiên bản yt-dlp.')
