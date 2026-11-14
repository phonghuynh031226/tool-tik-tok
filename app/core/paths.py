"""Project-local paths, including PyInstaller writable and resource roots.

Reject symlinks and all Windows reparse points (including junctions), even when
they point inside the root. No directory is created here. Filesystem writers
must still guard against concurrent path replacement after validation (TOCTOU).
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def _reject_links(path: Path) -> None:
    # Inspect original components before resolve/normalization can hide a link.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        attributes = getattr(info, 'st_file_attributes', 0)
        if stat.S_ISLNK(info.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Không cho phép symlink, junction hoặc reparse point.')


def _checked_absolute(path: Path) -> Path:
    raw = path if path.is_absolute() else Path.cwd() / path
    _reject_links(raw)
    normalized = Path(os.path.abspath(raw))
    _reject_links(normalized)
    return normalized.resolve(strict=False)


def project_root() -> Path:
    """Writable app root: source directory, or directory containing frozen exe."""
    if getattr(sys, 'frozen', False):
        return _checked_absolute(Path(sys.executable).parent)
    return _checked_absolute(Path(__file__).absolute().parents[2])


def resource_root() -> Path:
    """Bundled assets may be in _MEIPASS; never use it for persistent data."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return _checked_absolute(Path(sys._MEIPASS))
    return project_root()


def default_download_directory() -> Path:
    """Persistent downloads beside source/exe, independent of TEMP/TMP and cwd."""
    return safe_path('downloads')


def resolve_download_directory(value: str | Path | None = None) -> Path:
    """Normalize a project-local destination, including the old UI default.

    The UI historically passed .tmp/downloads explicitly. Treat exactly that
    legacy default (relative or absolute) as downloads; preserve custom paths.
    This only returns a path: it never moves, deletes or reads old media.
    """
    if value is None:
        return default_download_directory()
    base = project_root()
    candidate = safe_path(value, root=base)
    if candidate == base / '.tmp' / 'downloads':
        return safe_path('downloads', root=base)
    return candidate


def safe_path(*parts: str | Path, root: Path | None = None) -> Path:
    """Normalize a path under root, rejecting escapes and existing links.

    Relative paths are relative to root, never the process working directory.
    Absolute paths are accepted only if they remain inside root. Missing leaf
    files/directories are permitted; this function never creates them.
    """
    base = project_root() if root is None else _checked_absolute(Path(root))
    candidate = base
    for part in parts:
        fragment = Path(part)
        if os.name == 'nt':
            # Drive-relative paths, rooted paths without a drive, and NTFS streams
            # have ambiguous or special semantics and are not application paths.
            if (fragment.drive and not fragment.is_absolute()) or (fragment.root and not fragment.drive):
                raise ValueError('Đường dẫn Windows phải có gốc rõ ràng.')
            if any(':' in item for item in fragment.parts[1 if fragment.anchor else 0:]):
                raise ValueError('Không cho phép luồng dữ liệu NTFS trong đường dẫn.')
        candidate = candidate / fragment
    result = _checked_absolute(candidate)
    if not result.is_relative_to(base):
        raise ValueError('Đường dẫn nằm ngoài thư mục gốc của ứng dụng.')
    return result
