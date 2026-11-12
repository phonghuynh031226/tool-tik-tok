"""Real synchronous TikTokService. Run on a worker; no automatic upload/update.

The public progress callback remains float per contracts.py. Optional on_details
supplies bytes/speed/ETA for UI presentation without changing that frozen contract.
No watermark-removal transform, DRM bypass or watermark-free claim is performed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
from time import monotonic, sleep
from typing import Callable, TypeVar

import yt_dlp
from yt_dlp.utils import YoutubeDLError

from app.contracts import DownloadResult, ProgressCallback, VideoMeta
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import AppError, ContentInvalid, DownloadFailed
from ._process import local_tool
from .errors import failure, map_error
from .probe import positive_number, probe_video
from .url import extract_video_id, resolve_url

T = TypeVar('T')
MAX_RETRIES = 3


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    fraction: float
    downloaded_bytes: int
    total_bytes: int | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    phase: str

    @property
    def percent(self) -> float:
        return self.fraction * 100


class _QuietLogger:
    # SDK errors/warnings may contain signed CDN URLs or cookies. Never log them.
    def debug(self, message): pass
    def info(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def wait_backoff(delay: float, cancel_token: CancelToken) -> None:
    deadline = monotonic() + delay
    while True:
        cancel_token.raise_if_cancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(0.05, remaining))


def _retry(operation: Callable[[], T], token: CancelToken, callback_errors: list[BaseException] | None = None) -> T:
    for attempt in range(MAX_RETRIES + 1):
        token.raise_if_cancelled()
        try:
            result = operation()
            token.raise_if_cancelled()
            return result
        except Exception as error:
            if callback_errors:
                raise callback_errors[0]
            token.raise_if_cancelled()
            if not isinstance(error, (AppError, YoutubeDLError, OSError)):
                raise
            mapped = map_error(error)
            if not mapped.retryable or attempt == MAX_RETRIES:
                raise mapped from None
            wait_backoff(2.0 ** attempt, token)
    raise AssertionError('Unreachable')


def _metadata(info, canonical_url: str) -> VideoMeta:
    video_id = extract_video_id(canonical_url)
    if not isinstance(info, dict) or str(info.get('id')) != video_id:
        raise failure(ContentInvalid, 'Metadata TikTok không hợp lệ hoặc mã video không khớp liên kết.')
    if info.get('_type', 'video') != 'video' or 'entries' in info or info.get('is_live') or info.get('has_drm'):
        raise failure(ContentInvalid, 'Chỉ hỗ trợ một video TikTok thông thường; không hỗ trợ slideshow, livestream, playlist hoặc DRM.')
    width, height = positive_number(info.get('width')), positive_number(info.get('height'))
    if width is None or height is None:
        for item in reversed(info.get('formats') or []):
            if not isinstance(item, dict):
                continue
            w, h = positive_number(item.get('width')), positive_number(item.get('height'))
            if w and h:
                width, height = w, h
                break
    return VideoMeta(
        video_id, canonical_url, str(info.get('title') or f'TikTok {video_id}'),
        str(info.get('description') or ''), str(info.get('uploader') or info.get('creator') or info.get('uploader_id') or ''),
        info.get('thumbnail') if isinstance(info.get('thumbnail'), str) else None,
        positive_number(info.get('duration')), int(width) if width else None, int(height) if height else None,
    )


class TikTokService:
    def __init__(self, *, on_details: Callable[[DownloadProgress], None] | None = None) -> None:
        self._on_details = on_details
        self.latest_progress: DownloadProgress | None = None

    def _options(self) -> dict:
        cache = safe_path('.cache', 'yt-dlp')
        cache.mkdir(parents=True, exist_ok=True)
        return {
            'quiet': True, 'no_warnings': True, 'logger': _QuietLogger(),
            'cachedir': str(cache), 'noplaylist': True, 'allowed_extractors': ['^TikTok$'],
            'geo_bypass': False, 'allow_unplayable_formats': False,
            'usenetrc': False, 'cookiefile': None, 'cookiesfrombrowser': None,
            'retries': 0, 'fragment_retries': 0, 'extractor_retries': 0,
            'file_access_retries': 0, 'socket_timeout': 15, 'concurrent_fragment_downloads': 1,
        }

    def fetch_metadata(self, url: str) -> VideoMeta:
        def fetch() -> VideoMeta:
            canonical = resolve_url(url)
            with yt_dlp.YoutubeDL(self._options()) as ydl:
                info = ydl.extract_info(canonical, download=False)
            return _metadata(info, canonical)
        return _retry(fetch, CancelToken())

    def download(
        self, meta: VideoMeta, dest_dir: Path,
        on_progress: ProgressCallback, cancel_token: CancelToken,
    ) -> DownloadResult:
        cancel_token.raise_if_cancelled()
        canonical = resolve_url(meta.url)
        if meta.video_id != extract_video_id(canonical):
            raise failure(ContentInvalid, 'Mã video không khớp liên kết TikTok.')
        dest = safe_path(dest_dir)
        target = safe_path(dest, f'{meta.video_id}.mp4')
        callback_errors: list[BaseException] = []
        last_fraction = 0.0

        def emit(fraction: float, downloaded: int = 0, total: int | None = None,
                 speed: float | None = None, eta: float | None = None, phase: str = 'downloading') -> None:
            nonlocal last_fraction
            cancel_token.raise_if_cancelled()
            last_fraction = min(1.0, max(last_fraction, fraction))
            detail = DownloadProgress(last_fraction, downloaded, total, speed, eta, phase)
            self.latest_progress = detail
            try:
                on_progress(last_fraction)
                cancel_token.raise_if_cancelled()
                if self._on_details is not None:
                    self._on_details(detail)
            except BaseException as error:
                callback_errors.append(error)
                raise
            cancel_token.raise_if_cancelled()

        def progress_hook(data: dict) -> None:
            cancel_token.raise_if_cancelled()
            status = data.get('status')
            if status not in {'downloading', 'finished'}:
                return
            downloaded = int(positive_number(data.get('downloaded_bytes')) or 0)
            total_value = positive_number(data.get('total_bytes')) or positive_number(data.get('total_bytes_estimate'))
            total = int(total_value) if total_value else None
            fraction = min(downloaded / total, 1.0) * 0.95 if total else last_fraction
            if status == 'finished':
                fraction = 0.95
            emit(fraction, downloaded, total, positive_number(data.get('speed')), positive_number(data.get('eta')))

        emit(0.0)
        if target.is_file():
            try:
                existing = probe_video(target, cancel_token=cancel_token)
            except ContentInvalid:
                pass
            else:
                emit(1.0, existing.size, existing.size, phase='complete')
                return existing
        ffmpeg = local_tool('ffmpeg')
        # Check ffprobe before downloading any bytes; never auto-install binaries.
        local_tool('ffprobe')
        dest.mkdir(parents=True, exist_ok=True)

        def attempt() -> DownloadResult:
            stage = safe_path(tempfile.mkdtemp(prefix=f'.{meta.video_id}-', dir=dest))
            try:
                options = self._options() | {
                    # Single native HTTP(S) MP4 only: avoid SDK-managed ffmpeg
                    # merge/HLS processes that cannot poll our cancellation token.
                    'format': 'b[ext=mp4][protocol=https]/b[ext=mp4][protocol=http]/bv[ext=mp4][protocol=https]/bv[ext=mp4][protocol=http]',
                    'ffmpeg_location': str(ffmpeg.parent),
                    'outtmpl': str(stage / f'{meta.video_id}.%(ext)s'),
                    'paths': {'home': str(stage), 'temp': str(stage)},
                    'progress_hooks': [progress_hook],
                    'postprocessor_hooks': [lambda data: cancel_token.raise_if_cancelled()],
                    'overwrites': False, 'continuedl': False, 'fixup': 'never',
                    'writeinfojson': False, 'writethumbnail': False,
                }
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(canonical, download=True)
                cancel_token.raise_if_cancelled()
                _metadata(info, canonical)
                downloaded = safe_path(stage, f'{meta.video_id}.mp4')
                emit(0.97, phase='verifying')
                result = probe_video(downloaded, cancel_token=cancel_token)
                cancel_token.raise_if_cancelled()
                # Revalidate destination and source immediately before publishing.
                downloaded = safe_path(downloaded)
                downloaded.replace(safe_path(target))
                return replace(result, path=target)
            finally:
                shutil.rmtree(safe_path(stage))

        result = _retry(attempt, cancel_token, callback_errors)
        emit(1.0, result.size, result.size, phase='complete')
        return result
