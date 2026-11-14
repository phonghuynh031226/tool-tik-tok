"""DEV/TEST ONLY. Deterministic in-memory fakes; no network, secrets, or disk IO.

DownloadResult is a placeholder: its path does NOT point to a created MP4,
size is 0 and sha256 is the empty-byte digest. Never wire these as production
backends. No SDK, SQLite, OAuth, Gemini or media download is implemented here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any, Mapping

from app.contracts import (
    ChannelInfo, ChannelAccount, ChannelStats, VideoStats, DownloadResult, GeneratedContent, HistoryRecord, JobStatus,
    ProgressCallback, UploadRequest, UploadResult, VideoMeta,
)
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import AuthExpired, ContentInvalid, AccountNotFound, ScheduleInPast


def _tick() -> None:
    sleep(0.01)


def _progress(on_progress: ProgressCallback, cancel_token: CancelToken) -> None:
    for value in (0.0, 0.5, 1.0):
        cancel_token.raise_if_cancelled()
        _tick()
        cancel_token.raise_if_cancelled()
        on_progress(value)
        cancel_token.raise_if_cancelled()


class FakeTikTokService:
    def fetch_metadata(self, url: str) -> VideoMeta:
        _tick()
        return VideoMeta(
            'demo-001', 'https://www.tiktok.com/@demo/video/0000000000000000000',
            'Video mẫu phát triển', 'Mô tả video mẫu.', 'Demo Creator',
            None, 12.0, 1080, 1920,
        )

    def download(
        self, meta: VideoMeta, dest_dir: Path,
        on_progress: ProgressCallback, cancel_token: CancelToken,
    ) -> DownloadResult:
        cancel_token.raise_if_cancelled()
        path = safe_path(dest_dir, 'demo-001.mp4')
        _progress(on_progress, cancel_token)
        return DownloadResult(
            path, 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            12.0, 1080, 1920,
        )


class FakeContentGenerator:
    def list_models(self) -> list[str]:
        _tick()
        return ['fake-gemini-dev']

    def test_connection(self) -> bool:
        _tick()
        return True

    def generate(self, meta: VideoMeta, settings: Mapping[str, Any]) -> GeneratedContent:
        _tick()
        return GeneratedContent(
            'Tiêu đề mẫu — chỉ dùng phát triển',
            'Mô tả mẫu. Hãy xem và sửa nội dung trước khi xác nhận đăng.',
            ['demo', 'shorts'], ['demo', 'video mẫu'],
        )


class FakeYouTubeService:
    """V2 account/statistics fixtures; no browser, network, disk or real publication."""
    def __init__(self) -> None:
        self._connected = False
        self._accounts = {
            'fake-channel-dev': ChannelAccount('fake-channel-dev', 'Kênh mẫu DEV/TEST', is_default=True),
            'fake-channel-two': ChannelAccount('fake-channel-two', 'Kênh mẫu Shorts DEV/TEST'),
            'fake-channel-expired': ChannelAccount('fake-channel-expired', 'Kênh hết hạn DEV/TEST', status='expired'),
        }
        self._default_id = 'fake-channel-dev'
        self._serial = 3
        self._upload_serial = 0
        self._scheduled = {}
        self._cache = FakeStatsCache()
        for index, channel_id in enumerate(self._accounts, 1):
            self._seed_stats(channel_id, index)

    def _seed_stats(self, channel_id, index):
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._cache.save_channel_stats(ChannelStats(channel_id, 12500 * index,
            850000 * index, 15, False, stamp))
        self._cache.save_videos(channel_id, [VideoStats(
            video_id=f'fake-{index}-video-{number:02d}', title=f'Video mẫu {number} DEV/TEST',
            published_at=stamp - timedelta(days=number), privacy_status=('private' if number % 4 == 0 else 'public'),
            duration_seconds=20 + number * 7, views=number * number * 113,
            likes=None if number % 5 == 0 else number * 17,
            comments=None if number % 7 == 0 else number * 3, fetched_at=stamp,
        ) for number in range(1, 16)])

    def _account(self, channel_id, *, connected=True):
        if channel_id not in self._accounts:
            raise AccountNotFound()
        account = self._accounts[channel_id]
        if connected and account.status != 'connected':
            raise AuthExpired()
        return account

    def connect(self) -> ChannelInfo:
        _tick()
        self._account(self._default_id, connected=False).status = 'connected'
        self._connected = True
        return self.get_channel()

    def disconnect(self) -> None:
        _tick()
        self._connected = False
        if self._default_id in self._accounts:
            self._accounts[self._default_id].status = 'expired'

    def get_channel(self) -> ChannelInfo:
        if not self._connected:
            raise AuthExpired()
        account = self._account(self._default_id)
        return ChannelInfo(account.id, account.title)

    def list_accounts(self) -> list[ChannelAccount]:
        return deepcopy(list(self._accounts.values()))

    def add_account(self) -> ChannelAccount:
        self._serial += 1
        channel_id = f'fake-channel-dev-{self._serial}'
        account = ChannelAccount(channel_id, f'Kênh thêm {self._serial} DEV/TEST')
        if not self._accounts:
            self._default_id = channel_id
            account.is_default = True
        self._accounts[channel_id] = account
        self._seed_stats(channel_id, self._serial)
        return deepcopy(account)

    def remove_account(self, channel_id: str) -> None:
        self._account(channel_id, connected=False)
        del self._accounts[channel_id]
        self._scheduled = {key: value for key, value in self._scheduled.items() if value[1] != channel_id}
        if channel_id == self._default_id:
            self._default_id = next((key for key, value in self._accounts.items() if value.status == 'connected'),
                                    next(iter(self._accounts), None))
            if self._default_id is not None:
                self._accounts[self._default_id].is_default = True
            else:
                self._connected = False

    def set_default_account(self, channel_id: str) -> None:
        self._account(channel_id)
        for account in self._accounts.values():
            account.is_default = account.id == channel_id
        self._default_id = channel_id

    def get_channel_stats(self, channel_id: str, force_refresh: bool = False) -> ChannelStats:
        self._account(channel_id)
        _tick()
        return self._cache.load_channel_stats(channel_id)

    def list_channel_videos(self, channel_id: str, limit: int = 50, force_refresh: bool = False) -> list[VideoStats]:
        self._account(channel_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError('limit phải là số nguyên không âm.')
        _tick()
        return self._cache.load_videos(channel_id)[:limit]

    def upload(self, req: UploadRequest, on_progress: ProgressCallback,
               cancel_token: CancelToken) -> UploadResult:
        cancel_token.raise_if_cancelled()
        if req.channel_id is None:
            channel = self.get_channel()
        else:
            account = self._account(req.channel_id)
            channel = ChannelInfo(account.id, account.title)
        if not req.rights_confirmed:
            raise ContentInvalid()
        if req.publish_at is not None:
            if not isinstance(req.publish_at, datetime) or req.publish_at.tzinfo is None or req.publish_at.utcoffset() is None:
                raise ContentInvalid('Thời điểm hẹn phải có múi giờ.')
            if req.publish_at <= datetime.now(timezone.utc):
                raise ScheduleInPast()
            if req.privacy != 'private':
                raise ContentInvalid('Video hẹn giờ phải có privacy private.')
        _progress(on_progress, cancel_token)
        status = JobStatus.SCHEDULED if req.publish_at is not None else JobStatus.UPLOADED
        video_id = 'fake-video-dev'
        if req.publish_at is not None:
            self._upload_serial += 1
            video_id = f'fake-scheduled-{self._upload_serial}'
            self._scheduled[video_id] = (req.publish_at, channel.id)
        return UploadResult(video_id, f'https://www.youtube.com/watch?v={video_id}', channel.id, status)

    def check_processing(self, video_id: str) -> str:
        self.get_channel()
        _tick()
        return 'processing' if video_id in self._scheduled else 'succeeded'

    def sync_scheduled(self) -> list[UploadResult]:
        now = datetime.now(timezone.utc)
        published = []
        for video_id, (publish_at, channel_id) in list(self._scheduled.items()):
            if publish_at <= now:
                published.append(UploadResult(video_id, f'https://www.youtube.com/watch?v={video_id}', channel_id))
                del self._scheduled[video_id]
        return published


class FakeHistoryRepository:
    def __init__(self) -> None:
        self._records: dict[int, HistoryRecord] = {}
        self._next_id = 1

    def add(self, record: Mapping[str, Any]) -> int:
        job_id = self._next_id
        self._next_id += 1
        self._records[job_id] = deepcopy(dict(record)) | {'id': job_id}
        return job_id

    def update(self, job_id: int, changes: Mapping[str, Any]) -> None:
        self._records[job_id].update(deepcopy(dict(changes)))
        self._records[job_id]['id'] = job_id

    def list_scheduled(self) -> list[HistoryRecord]:
        return deepcopy([record for record in reversed(self._records.values())
                         if record.get('status', record.get('processing_status')) == JobStatus.SCHEDULED])

    def find_by_video_id(self, video_id: str) -> HistoryRecord | None:
        return self._find('video_id', video_id)

    def find_by_hash(self, sha256: str) -> HistoryRecord | None:
        return self._find('sha256', sha256)

    def _find(self, key: str, value: str) -> HistoryRecord | None:
        return next((deepcopy(record) for record in reversed(self._records.values())
                     if record.get(key) == value), None)

    def search(self, query: str, limit: int = 100, offset: int = 0) -> list[HistoryRecord]:
        needle = query.casefold()
        records = [record for record in reversed(self._records.values()) if any(
            needle in str(record.get(key, '')).casefold() for key in ('video_id', 'title', 'url')
        )]
        return self._page(records, limit, offset)

    def list(
        self, limit: int = 100, offset: int = 0, status: JobStatus | None = None,
    ) -> list[HistoryRecord]:
        records = [record for record in reversed(self._records.values())
                   if status is None or record.get('status') == status]
        return self._page(records, limit, offset)

    @staticmethod
    def _page(records: list[HistoryRecord], limit: int, offset: int) -> list[HistoryRecord]:
        if limit < 0 or offset < 0:
            raise ValueError('limit và offset phải không âm.')
        return deepcopy(records[offset:offset + limit])


class FakeSecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class FakeSettingsStore:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._values.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._values[key] = deepcopy(value)


class FakeStatsCache:
    """In-memory V2 snapshots, intentionally isolated per instance."""
    def __init__(self):
        self._channels = {}
        self._videos = {}

    def save_channel_stats(self, stats: ChannelStats) -> None:
        self._channels[stats.channel_id] = deepcopy(stats)

    def load_channel_stats(self, channel_id: str) -> ChannelStats | None:
        return deepcopy(self._channels.get(channel_id))

    def save_videos(self, channel_id: str, videos: list[VideoStats]) -> None:
        self._videos[channel_id] = deepcopy(videos)

    def load_videos(self, channel_id: str) -> list[VideoStats]:
        return deepcopy(self._videos.get(channel_id, []))
