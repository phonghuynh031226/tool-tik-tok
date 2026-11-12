"""Explicit user-initiated update of yt-dlp in project .venv only.

UI may display get_ytdlp_version(). Call update_ytdlp(user_requested=True) from
the update button's worker. No update is performed on import/service startup.
Restart the application to use updated code; requirements.txt is not modified.
"""

from __future__ import annotations

import os
from yt_dlp.version import __version__

from app.core.cancel import CancelToken
from app.core.paths import project_root, safe_path
from app.errors import ContentInvalid, DownloadFailed
from ._process import project_environment, run_process
from .errors import failure


def get_ytdlp_version() -> str:
    return __version__


def update_ytdlp(*, user_requested: bool = False, cancel_token: CancelToken | None = None) -> str:
    if user_requested is not True:
        raise failure(ContentInvalid, 'Chỉ cập nhật yt-dlp sau khi người dùng bấm nút cập nhật.')
    token = cancel_token or CancelToken()
    token.raise_if_cancelled()
    root = project_root()
    interpreter = safe_path('.venv', 'Scripts/python.exe' if os.name == 'nt' else 'bin/python', root=root)
    if not interpreter.is_file():
        raise failure(DownloadFailed, 'Không có Python trong .venv của dự án. Hãy chuẩn bị .venv trước khi cập nhật yt-dlp; ứng dụng không sửa Python toàn cục.')
    environment = project_environment(root)
    # --isolated alone still loads global/site configuration. Disable ALL files,
    # otherwise install.target/prefix/log may redirect writes outside the project.
    environment['PIP_CONFIG_FILE'] = os.devnull
    command = [str(interpreter), '-I', '-X', f'pycache_prefix={environment["PYTHONPYCACHEPREFIX"]}',
               '-m', 'pip', '--isolated', '--require-virtualenv',
               '--disable-pip-version-check', '--cache-dir', environment['PIP_CACHE_DIR'],
               'install', '--upgrade', '--no-user', '--no-input', '--only-binary=:all:',
               '--no-deps', 'yt-dlp']
    run_process(command, cancel_token=token, timeout=600, env=environment)
    return 'Đã cập nhật yt-dlp trong .venv của dự án. Vui lòng khởi động lại ứng dụng để dùng phiên bản mới.'
