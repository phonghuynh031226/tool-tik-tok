"""DEV/TEST ONLY. Deterministic in-memory fakes; no network, secrets, or disk IO.

DownloadResult is a placeholder: its path does NOT point to a created MP4,
size is 0 and sha256 is the empty-byte digest. Never wire these as production
backends. No SDK, SQLite, OAuth, Gemini or media download is implemented here.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import sleep
from typing import Any, Mapping

from app.contracts import (
    ChannelInfo, DownloadResult, GeneratedContent, HistoryRecord, JobStatus,
    ProgressCallback, UploadRequest, UploadResult, VideoMeta,
)
from app.core.cancel import CancelToken
from app.core.paths import safe_path
from app.errors import AuthExpired, ContentInvalid


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
    def __init__(self) -> None:
        self._connected = False

    def connect(self) -> ChannelInfo:
        _tick()
        self._connected = True
        return self.get_channel()

    def disconnect(self) -> None:
        _tick()
        self._connected = False

    def get_channel(self) -> ChannelInfo:
        if not self._connected:
            raise AuthExpired()
        return ChannelInfo('fake-channel-dev', 'Kênh mẫu DEV/TEST')

    def upload(
        self, req: UploadRequest, on_progress: ProgressCallback,
        cancel_token: CancelToken,
    ) -> UploadResult:
        cancel_token.raise_if_cancelled()
        channel = self.get_channel()
        if not req.rights_confirmed:
            raise ContentInvalid()
        _progress(on_progress, cancel_token)
        return UploadResult('fake-video-dev', 'https://www.youtube.com/watch?v=fake-video-dev', channel.id)

    def check_processing(self, video_id: str) -> str:
        self.get_channel()
        _tick()
        return 'succeeded'


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
