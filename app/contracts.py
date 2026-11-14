"""Frozen Step 0 contracts shared by UI and backend.

Changes require a proposal in docs/CONTRACT_CHANGES.md. Methods are synchronous;
UI callers run slow work in workers. Progress is a float in [0.0, 1.0], invoked
on the calling thread; callback exceptions propagate. Paths are pathlib.Path,
durations are seconds, dimensions are pixels, size is bytes, sha256 is hex.
Unknown source duration/dimensions use None. Tags/hashtags do not include '#'.
No implementation, credentials, external SDK objects, or Qt types belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from app.core.cancel import CancelToken

ProgressCallback = Callable[[float], None]
HistoryRecord = dict[str, Any]


class JobStatus(str, Enum):
    NEW = 'NEW'
    METADATA_OK = 'METADATA_OK'
    DOWNLOADED = 'DOWNLOADED'
    CONTENT_READY = 'CONTENT_READY'
    UPLOADING = 'UPLOADING'
    UPLOADED = 'UPLOADED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'
    SCHEDULED = 'SCHEDULED'


@dataclass(slots=True)
class VideoMeta:
    video_id: str
    url: str
    title: str
    description: str
    author: str
    thumbnail_url: str | None
    duration: float | None
    width: int | None
    height: int | None


@dataclass(slots=True)
class DownloadResult:
    path: Path
    size: int
    sha256: str
    duration: float | None
    width: int | None
    height: int | None


@dataclass(slots=True)
class GeneratedContent:
    title: str
    description: str
    hashtags: list[str]
    tags: list[str]


@dataclass(slots=True)
class UploadRequest:
    path: Path
    title: str
    description: str
    tags: list[str]
    privacy: str = 'private'  # private | unlisted | public; validate in implementation
    made_for_kids: bool = False
    category_id: str = '22'
    default_language: str = 'vi'
    rights_confirmed: bool = False  # UI must separately confirm the upload action.
    publish_at: datetime | None = None  # Must be timezone-aware when supplied.
    channel_id: str | None = None  # None selects the default account.


@dataclass(slots=True)
class UploadResult:
    video_id: str
    url: str
    channel_id: str
    status: JobStatus = JobStatus.UPLOADED


@dataclass(slots=True)
class ChannelInfo:
    id: str
    title: str


@dataclass(slots=True)
class ChannelAccount:
    id: str = ''
    title: str = ''
    thumbnail_url: str | None = None
    is_default: bool = False
    status: Literal['connected', 'expired', 'error'] = 'connected'


@dataclass(slots=True)
class ChannelStats:
    channel_id: str = ''
    subscribers: int | None = None
    total_views: int = 0
    video_count: int = 0
    subscribers_hidden: bool = False
    fetched_at: datetime | None = None


@dataclass(slots=True)
class VideoStats:
    video_id: str = ''
    title: str = ''
    thumbnail_url: str | None = None
    published_at: datetime | None = None
    scheduled_at: datetime | None = None
    privacy_status: str = 'private'
    duration_seconds: float = 0.0
    views: int = 0
    likes: int | None = None
    comments: int | None = None
    fetched_at: datetime | None = None


@runtime_checkable
class TikTokService(Protocol):
    def fetch_metadata(self, url: str) -> VideoMeta: ...

    def download(
        self, meta: VideoMeta, dest_dir: Path,
        on_progress: ProgressCallback, cancel_token: CancelToken,
    ) -> DownloadResult: ...


@runtime_checkable
class ContentGenerator(Protocol):
    def list_models(self) -> list[str]: ...

    def test_connection(self) -> bool: ...

    def generate(self, meta: VideoMeta, settings: Mapping[str, Any]) -> GeneratedContent: ...


@runtime_checkable
class YouTubeService(Protocol):
    def connect(self) -> ChannelInfo: ...

    def disconnect(self) -> None: ...

    def get_channel(self) -> ChannelInfo: ...

    def upload(
        self, req: UploadRequest, on_progress: ProgressCallback,
        cancel_token: CancelToken,
    ) -> UploadResult: ...

    def check_processing(self, video_id: str) -> str:
        """Return YouTube processing status: processing/succeeded/failed/terminated."""
        ...

    def list_accounts(self) -> list[ChannelAccount]: ...

    def add_account(self) -> ChannelAccount: ...

    def remove_account(self, channel_id: str) -> None: ...

    def set_default_account(self, channel_id: str) -> None: ...

    def get_channel_stats(self, channel_id: str, force_refresh: bool = False) -> ChannelStats: ...

    def list_channel_videos(self, channel_id: str, limit: int = 50, force_refresh: bool = False) -> list[VideoStats]: ...

    def sync_scheduled(self) -> list[UploadResult]:
        """Return scheduled uploads whose published state changed on this sync."""
        ...


@runtime_checkable
class HistoryRepository(Protocol):
    """Nonsecret records; id is int, video_id/sha256 are str, status is JobStatus.

    add returns a new id; update preserves id and raises KeyError if absent.
    find returns the newest matching record or None. search is case-insensitive
    across video_id/title/url. list/search return newest first, offset >= 0 and
    limit >= 0; callers receive detached records. Extra nonsecret fields allowed.
    """

    def add(self, record: Mapping[str, Any]) -> int: ...

    def update(self, job_id: int, changes: Mapping[str, Any]) -> None: ...

    def find_by_video_id(self, video_id: str) -> HistoryRecord | None: ...

    def find_by_hash(self, sha256: str) -> HistoryRecord | None: ...

    def search(self, query: str, limit: int = 100, offset: int = 0) -> list[HistoryRecord]: ...

    def list(
        self, limit: int = 100, offset: int = 0, status: JobStatus | None = None,
    ) -> list[HistoryRecord]: ...

    def list_scheduled(self) -> list[HistoryRecord]: ...


@runtime_checkable
class SecretStore(Protocol):
    """Missing key returns None; deleting a missing key is a no-op."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


@runtime_checkable
class SettingsStore(Protocol):
    """Nonsecret settings only; missing keys return default."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...


@runtime_checkable
class StatsCache(Protocol):
    """Detached snapshots; missing channel returns None, missing videos return [].

    Datetimes are timezone-aware when supplied; fetched_at=None means unknown.
    save_videos replaces the channel's complete cached snapshot, including [].
    """

    def save_channel_stats(self, stats: ChannelStats) -> None: ...

    def load_channel_stats(self, channel_id: str) -> ChannelStats | None: ...

    def save_videos(self, channel_id: str, videos: list[VideoStats]) -> None: ...

    def load_videos(self, channel_id: str) -> list[VideoStats]: ...
