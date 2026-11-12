"""Inspect download destinations without authorizing or performing external IO."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from app.core.paths import project_root, safe_path


@dataclass(frozen=True, slots=True)
class DownloadDirectoryAssessment:
    path: Path
    requires_user_confirmation: bool


class PathConfirmationRequired(ValueError):
    def __init__(self, assessment: DownloadDirectoryAssessment):
        super().__init__('Thư mục nằm ngoài dự án; cần người dùng xác nhận trước khi lưu lựa chọn.')
        self.assessment = assessment
        self.requires_user_confirmation = True


def assess_download_directory(value: str | Path) -> DownloadDirectoryAssessment:
    """Reject links/ambiguous paths; return a confirmation flag for external paths.

    This does not create directories or authorize any reads/writes outside project.
    Existing download backend still enforces its own project-local boundary.
    """
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError('Thư mục tải không hợp lệ.')
    text = str(value)
    if any(ord(char) < 32 for char in text):
        raise ValueError('Thư mục tải không hợp lệ.')
    root = project_root()
    raw = Path(value)
    if os.name == 'nt':
        if (raw.drive and not raw.is_absolute()) or (raw.root and not raw.drive):
            raise ValueError('Đường dẫn Windows phải có gốc rõ ràng.')
        if any(':' in part for part in raw.parts[1 if raw.anchor else 0:]):
            raise ValueError('Không cho phép luồng dữ liệu NTFS.')
    if not raw.is_absolute():
        raw = root / raw
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Không cho phép symlink hoặc junction trong thư mục tải.')
    normalized = Path(os.path.abspath(raw)).resolve(strict=False)
    if normalized.exists() and not normalized.is_dir():
        raise ValueError('Đường dẫn tải phải là thư mục.')
    outside = not normalized.is_relative_to(root)
    if not outside:
        normalized = safe_path(normalized)
    return DownloadDirectoryAssessment(normalized, outside)
