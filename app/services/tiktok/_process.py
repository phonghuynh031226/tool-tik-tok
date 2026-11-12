"""Project-local, cancellable subprocesses without shell or visible console."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from time import monotonic

from app.core.cancel import CancelToken
from app.core.paths import project_root, safe_path
from app.errors import DownloadFailed
from .errors import failure


def local_tool(name: str) -> Path:
    if name not in {'ffmpeg', 'ffprobe'}:
        raise ValueError('Unsupported tool')
    tool = safe_path('bin', name + ('.exe' if os.name == 'nt' else ''), root=project_root())
    if not tool.is_file():
        raise failure(DownloadFailed, 'Thiếu công cụ xử lý video. Hãy đặt ffmpeg.exe và ffprobe.exe của bộ FFmpeg vào thư mục bin/ của dự án. Ứng dụng không tự cài đặt.')
    return tool


def project_environment(root: Path | None = None) -> dict[str, str]:
    root = project_root() if root is None else root
    # Some subprocess tools read these directly even in isolated/config-free mode.
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith('PIP_') and key.upper() != 'FFREPORT'}
    locations = {
        'TEMP': safe_path('.tmp', root=root), 'TMP': safe_path('.tmp', root=root),
        'TMPDIR': safe_path('.tmp', root=root),
        'PIP_CACHE_DIR': safe_path('.cache/pip', root=root),
        'PYTHONPYCACHEPREFIX': safe_path('.cache/pycache', root=root),
    }
    for key, path in locations.items():
        path.mkdir(parents=True, exist_ok=True)
        environment[key] = str(path)
    environment['PYTHONNOUSERSITE'] = '1'
    # Do not let inherited Python paths redirect the selected local interpreter.
    environment.pop('PYTHONHOME', None)
    environment.pop('PYTHONPATH', None)
    return environment


def run_process(
    command: list[str], *, cancel_token: CancelToken | None = None,
    timeout: float = 120, env: dict[str, str] | None = None,
    reject_stderr: bool = False,
) -> str:
    token = cancel_token or CancelToken()
    token.raise_if_cancelled()
    process = None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            cwd=str(project_root()), env=env if env is not None else project_environment(),
        )
        deadline = monotonic() + timeout
        while True:
            token.raise_if_cancelled()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise failure(DownloadFailed, 'Công cụ xử lý đã vượt thời gian chờ. Vui lòng thử lại thủ công.')
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        token.raise_if_cancelled()
        if process.returncode != 0 or reject_stderr and stderr.strip():
            raise failure(DownloadFailed, 'Công cụ xử lý không hoàn tất. Hãy kiểm tra tệp video hoặc công cụ trong dự án.')
        return stdout
    except OSError:
        raise failure(DownloadFailed, 'Không chạy được công cụ trong dự án. Hãy kiểm tra tệp thực thi và quyền truy cập.') from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
