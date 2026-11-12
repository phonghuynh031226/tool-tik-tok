"""Decode/count video frames with bundled ffprobe, validate MP4 and hash bytes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from app.contracts import DownloadResult
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import ContentInvalid, DownloadFailed
from ._process import local_tool, run_process
from .errors import failure


def positive_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def probe_video(path: Path, *, cancel_token: CancelToken | None = None, timeout: float = 120) -> DownloadResult:
    token = cancel_token or CancelToken()
    token.raise_if_cancelled()
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise failure(ContentInvalid, 'Tệp video không tồn tại hoặc không có dữ liệu.')
    executable = local_tool('ffprobe')
    command = [str(executable), '-v', 'error', '-protocol_whitelist', 'file',
               '-select_streams', 'v:0', '-count_frames', '-show_streams', '-show_format',
               '-of', 'json', str(path)]
    try:
        output = run_process(command, cancel_token=token, timeout=timeout, reject_stderr=True)
    except DownloadFailed:
        raise failure(ContentInvalid, 'Tệp MP4 bị lỗi hoặc không giải mã được. Vui lòng tải lại video.') from None
    try:
        info = json.loads(output)
        stream = next(stream for stream in info['streams'] if stream.get('codec_type') == 'video')
        container = info['format']
        duration = positive_number(stream.get('duration'))
        # Invalid supplied values are corruption, not an excuse to trust fallback.
        if stream.get('duration') in (None, 'N/A'):
            duration = positive_number(container.get('duration'))
        width = positive_number(stream.get('width'))
        height = positive_number(stream.get('height'))
        frames = positive_number(stream.get('nb_read_frames'))
        if not all((duration, width, height, frames)) or not stream.get('codec_name') or stream['codec_name'] in {'unknown', 'none'}:
            raise ValueError('Undecodable video')
        if 'mp4' not in container.get('format_name', '').split(','):
            raise ValueError('Not an MP4 container')
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError):
        raise failure(ContentInvalid, 'Tệp không phải MP4 phát được hoặc thiếu thời lượng/kích thước video hợp lệ.') from None
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open('rb') as source:
            while True:
                token.raise_if_cancelled()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        raise failure(DownloadFailed, 'Không thể đọc tệp video để tính SHA-256.') from None
    token.raise_if_cancelled()
    return DownloadResult(path, size, digest.hexdigest(), duration, int(width), int(height))
