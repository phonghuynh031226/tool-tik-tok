"""Shared application state representing the current active Job."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import logging
import re

from PySide6.QtCore import QObject, Signal

from app.contracts import (
    DownloadResult, GeneratedContent, JobStatus, UploadRequest,
    UploadResult, VideoMeta,
)
from app.services.youtube.validators import validate_title, validate_description, validate_tags
from app.errors import ContentInvalid

logger = logging.getLogger('TikTokYouTubeStudio.events')


def format_hashtags(tags):
    return ' '.join(dict.fromkeys('#' + word.lstrip('#') for tag in tags
                    for word in tag.replace(',', ' ').split() if word.lstrip('#')))


class JobState(QObject):
    """Central observable state for the active processing pipeline.

    All pages (Dashboard, TikTok, AI, YouTube, etc.) interact with this
    single shared instance so inputs, downloads, and generated content
    persist seamlessly across view transitions.
    """

    job_changed = Signal()
    meta_changed = Signal(object)
    video_ready = Signal(str)
    content_changed = Signal(object)
    upload_changed = Signal(object)
    status_changed = Signal(str)
    dry_run_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._url: str = ""
        self._meta: Optional[VideoMeta] = None
        self._download_result: Optional[DownloadResult] = None
        self._local_video_path: Optional[Path] = None
        self._content: Optional[GeneratedContent] = None
        self._original_title: str = ""
        self._original_description: str = ""
        self._title: str = ""
        self._description: str = ""
        self._hashtags: list[str] = []
        self._tags: list[str] = []
        self._privacy: str = "private"  # Default 'private' per requirements
        self._made_for_kids: Optional[bool] = None  # None: NOT chosen yet, mandatory
        self._rights_confirmed: bool = False  # Mandatory checkbox
        self._upload_result: Optional[UploadResult] = None
        self._status: JobStatus = JobStatus.NEW
        self._error_message: Optional[str] = None
        self._history_id: Optional[int] = None
        self._dry_run: bool = False
        self.dry_run_result = None

    # Properties
    @property
    def url(self) -> str:
        return self._url

    @url.setter
    def url(self, val: str) -> None:
        self._url = val.strip()
        self.job_changed.emit()

    @property
    def meta(self) -> Optional[VideoMeta]:
        return self._meta

    @meta.setter
    def meta(self, val: Optional[VideoMeta]) -> None:
        self._meta = val
        if val:
            if not self._original_title:
                self._original_title = val.title
                self._title = val.title
            if not self._original_description:
                self._original_description = val.description
                self._description = val.description
            if self._status in (JobStatus.NEW, JobStatus.FAILED):
                self._status = JobStatus.METADATA_OK
        self.meta_changed.emit(self._meta)
        self.job_changed.emit()

    @property
    def download_result(self) -> Optional[DownloadResult]:
        return self._download_result

    @property
    def local_video_path(self) -> Optional[Path]:
        return self._local_video_path

    def set_download_result(self, result: DownloadResult) -> None:
        self._download_result = result
        self._local_video_path = result.path
        self._status = JobStatus.DOWNLOADED
        self.video_ready.emit(str(result.path))
        self.status_changed.emit(self._status.value)
        self.job_changed.emit()

    def set_local_file(self, path: Path) -> None:
        """User picked a local MP4 file from computer."""
        self._local_video_path = path
        self._status = JobStatus.DOWNLOADED
        if not self._meta:
            self._meta = VideoMeta(
                video_id=f"local-{path.stem}",
                url=f"file://{path.resolve()}",
                title=path.stem,
                description=f"Tải lên từ tập tin cục bộ: {path.name}",
                author="Cục bộ",
                thumbnail_url=None,
                duration=None,
                width=None,
                height=None,
            )
            self._original_title = path.stem
            self._title = path.stem
            self._original_description = self._meta.description
            self._description = self._meta.description
        self.video_ready.emit(str(path))
        self.status_changed.emit(self._status.value)
        self.meta_changed.emit(self._meta)
        self.job_changed.emit()

    @property
    def content(self) -> Optional[GeneratedContent]:
        return self._content

    def set_generated_content(self, content: GeneratedContent) -> None:
        logger.info('content_generated — nội dung sẵn sàng xem và sửa')
        self._content = content
        self._title = content.title
        self._description = content.description
        self._hashtags = list(content.hashtags)
        self._tags = list(content.tags)
        self._status = JobStatus.CONTENT_READY
        self.content_changed.emit(content)
        self.status_changed.emit(self._status.value)
        self.job_changed.emit()

    @property
    def original_title(self) -> str:
        return self._original_title

    @property
    def original_description(self) -> str:
        return self._original_description

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, val: str) -> None:
        self._title = val
        self.job_changed.emit()

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, val: str) -> None:
        self._description = val
        self.job_changed.emit()

    @property
    def hashtags(self) -> list[str]:
        return self._hashtags

    @hashtags.setter
    def hashtags(self, val: list[str]) -> None:
        self._hashtags = val
        self.job_changed.emit()

    @property
    def tags(self) -> list[str]:
        return self._tags

    @tags.setter
    def tags(self, val: list[str]) -> None:
        self._tags = val
        self.job_changed.emit()

    @property
    def privacy(self) -> str:
        return self._privacy

    @privacy.setter
    def privacy(self, val: str) -> None:
        if val in ("private", "unlisted", "public"):
            self._privacy = val
            self.job_changed.emit()

    @property
    def made_for_kids(self) -> Optional[bool]:
        return self._made_for_kids

    @made_for_kids.setter
    def made_for_kids(self, val: Optional[bool]) -> None:
        self._made_for_kids = val
        self.job_changed.emit()

    @property
    def rights_confirmed(self) -> bool:
        return self._rights_confirmed

    @rights_confirmed.setter
    def rights_confirmed(self, val: bool) -> None:
        self._rights_confirmed = bool(val)
        self.job_changed.emit()

    @property
    def status(self) -> JobStatus:
        return self._status

    @status.setter
    def status(self, val: JobStatus) -> None:
        self._status = val
        self.status_changed.emit(val.value)
        self.job_changed.emit()

    @property
    def upload_result(self) -> Optional[UploadResult]:
        return self._upload_result

    def set_upload_result(self, result: UploadResult) -> None:
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(result.video_id)) or not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', str(result.channel_id)):
            raise ValueError('YouTube chưa trả mã video/kênh hợp lệ.')
        self.dry_run_result = None
        self._upload_result = result
        self._status = JobStatus.UPLOADED
        self.upload_changed.emit(result)
        self.status_changed.emit(self._status.value)
        self.job_changed.emit()

    def set_dry_run_result(self, result) -> None:
        self.dry_run_result = result
        self._upload_result = None
        self._status = JobStatus.CONTENT_READY
        self.upload_changed.emit(result)
        self.status_changed.emit('DRY_RUN')  # UI-only presentation, not a contract enum.
        self.job_changed.emit()

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @error_message.setter
    def error_message(self, val: Optional[str]) -> None:
        self._error_message = val
        if val:
            self._status = JobStatus.FAILED
            self.status_changed.emit(self._status.value)
        self.job_changed.emit()

    def restore_original(self) -> None:
        """Restore title and description to the original raw video info."""
        if self._original_title:
            self._title = self._original_title
        if self._original_description:
            self._description = self._original_description
        self.job_changed.emit()

    def can_upload(self) -> tuple[bool, str]:
        """Check if upload prerequisites are met."""
        if not self._local_video_path or not self._local_video_path.exists():
            return False, "Chưa có file video để tải lên (hãy tải hoặc chọn MP4 từ máy)."
        if not self._title.strip():
            return False, "Tiêu đề video không được để trống."
        if len(self._title) > 100:
            return False, "Tiêu đề video không được vượt quá 100 ký tự."
        if self._made_for_kids is None:
            return False, "Bắt buộc phải chọn đối tượng người xem (Dành cho trẻ em hay Không)."
        if not self._rights_confirmed:
            return False, "Bắt buộc phải xác nhận bạn có quyền sử dụng video này."
        try:
            validate_title(self._title.strip())
            validate_description(self.upload_description())
            validate_tags(self._tags)
        except ContentInvalid as error:
            return False, error.user_message
        return True, ""

    def upload_description(self) -> str:
        hashtags = format_hashtags(self._hashtags)
        return self._description.strip() + ('\n\n' + hashtags if hashtags else '')

    def build_upload_request(self) -> UploadRequest:
        """Create an UploadRequest based on current state."""
        ok, reason = self.can_upload()
        if not ok:
            raise ValueError(reason)

        assert self._local_video_path is not None
        assert self._made_for_kids is not None

        # Format combined description with hashtags
        desc = self.upload_description()

        return UploadRequest(
            path=self._local_video_path,
            title=self._title.strip(),
            description=desc,
            tags=self._tags,
            privacy=self._privacy,
            made_for_kids=self._made_for_kids,
            rights_confirmed=self._rights_confirmed,
        )

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, val: bool) -> None:
        self._dry_run = bool(val)
        self.dry_run_changed.emit(self._dry_run)
        self.job_changed.emit()

    def load_from_record(self, record: dict) -> None:
        """Resume state from a stored history record."""
        self._history_id = record.get("id")
        self._url = record.get("url", "")
        self._title = record.get("title", "")
        self._description = record.get("description", "")
        self._hashtags = list(record.get("hashtags", []))
        self._tags = list(record.get("tags", []))
        self._privacy = record.get("privacy", "private")

        raw_status = record.get("status")
        if isinstance(raw_status, JobStatus):
            self._status = raw_status
        elif raw_status and hasattr(JobStatus, str(raw_status)):
            self._status = JobStatus(str(raw_status))
        elif raw_status and str(raw_status) in [s.value for s in JobStatus]:
            self._status = JobStatus(str(raw_status))

        path_str = record.get("path") or record.get("local_video_path")
        if path_str:
            p = Path(path_str)
            self._local_video_path = p
            if p.exists():
                self.video_ready.emit(str(p))

        vid_id = record.get("video_id")
        if vid_id and not self._meta:
            self._meta = VideoMeta(
                video_id=str(vid_id),
                url=self._url,
                title=self._title or f"Video {vid_id}",
                description=self._description,
                author="Lịch sử",
                thumbnail_url=None,
                duration=None,
                width=None,
                height=None,
            )
            self.meta_changed.emit(self._meta)

        self.status_changed.emit(self._status.value)
        self.job_changed.emit()

    def reset(self) -> None:
        """Reset state for a fresh job."""
        self._url = ""
        self._meta = None
        self._download_result = None
        self._local_video_path = None
        self._content = None
        self._original_title = ""
        self._original_description = ""
        self._title = ""
        self._description = ""
        self._hashtags = []
        self._tags = []
        self._privacy = "private"
        self._made_for_kids = None
        self._rights_confirmed = False
        self._upload_result = None
        self._status = JobStatus.NEW
        self._error_message = None
        self.dry_run_result = None
        self.upload_changed.emit(None)
        self.status_changed.emit(self._status.value)
        self.job_changed.emit()

