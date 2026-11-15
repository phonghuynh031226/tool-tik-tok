"""SQLite StatsCache snapshots; API credentials never enter these tables.

Extra window metadata distinguishes a complete/empty playlist from a limited
prefix. Snapshot rows and metadata are replaced in one transaction.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import ChannelStats, VideoStats
from app.core.paths import safe_path
from app.security.redaction import nonsecret_value
from .repository import SQLiteHistoryRepository


def _encode(value):
    result = asdict(value)
    for key, item in result.items():
        if isinstance(item, datetime):
            if item.tzinfo is None or item.utcoffset() is None:
                raise ValueError('Thời gian cache phải có múi giờ.')
            result[key] = item.isoformat()
    return nonsecret_value(result)


def _decode(row, model):
    value = dict(row)
    value.pop('position', None)
    if model is VideoStats:
        value.pop('channel_id', None)
    for key in ('fetched_at', 'published_at', 'scheduled_at'):
        if key in value and value[key] is not None:
            value[key] = datetime.fromisoformat(value[key])
    if model is ChannelStats:
        value['subscribers_hidden'] = bool(value['subscribers_hidden'])
    return model(**value)


@dataclass
class VideoWindow:
    videos: list[VideoStats]
    fetched_at: datetime | None
    requested_limit: int
    complete: bool


class SQLiteStatsCache:
    def __init__(self, path: Path | None = None):
        self.path = safe_path(path if path is not None else Path('data/app.db'))

    def save_channel_stats(self, stats: ChannelStats) -> None:
        values = _encode(stats)
        columns = ','.join(values)  # Fixed dataclass field names, never user SQL.
        with SQLiteHistoryRepository(self.path) as repo, repo._transaction():
            repo._db.execute(f'INSERT OR REPLACE INTO channel_stats ({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))

    def load_channel_stats(self, channel_id: str) -> ChannelStats | None:
        with SQLiteHistoryRepository(self.path) as repo:
            row = repo._db.execute('SELECT * FROM channel_stats WHERE channel_id = ?', (channel_id,)).fetchone()
            return _decode(row, ChannelStats) if row else None

    def save_videos(self, channel_id: str, videos: list[VideoStats]) -> None:
        stamp = min((video.fetched_at for video in videos if video.fetched_at is not None), default=datetime.now(timezone.utc))
        self.save_video_window(channel_id, videos, fetched_at=stamp, requested_limit=len(videos), complete=True)

    def load_videos(self, channel_id: str) -> list[VideoStats]:
        return self.load_video_window(channel_id).videos

    def save_video_window(self, channel_id, videos, *, fetched_at, requested_limit, complete):
        if type(requested_limit) is not int or requested_limit < 0 or type(complete) is not bool:
            raise ValueError('Phạm vi cache không hợp lệ.')
        encoded = [_encode(video) for video in videos]
        if len({item['video_id'] for item in encoded}) != len(encoded):
            raise ValueError('Cache không được chứa mã video trùng.')
        stamp = _encode(ChannelStats(fetched_at=fetched_at))['fetched_at']
        with SQLiteHistoryRepository(self.path) as repo, repo._transaction():
            repo._db.execute('DELETE FROM video_stats WHERE channel_id = ?', (channel_id,))
            for position, value in enumerate(encoded):
                value = value | {'channel_id': channel_id, 'position': position}
                columns = ','.join(value)
                repo._db.execute(f'INSERT INTO video_stats ({columns}) VALUES ({",".join("?" for _ in value)})', tuple(value.values()))
            repo._db.execute('INSERT OR REPLACE INTO video_cache_state(channel_id,fetched_at,requested_limit,complete) VALUES(?,?,?,?)',
                             (channel_id, stamp, requested_limit, int(complete)))

    def load_video_window(self, channel_id) -> VideoWindow:
        with SQLiteHistoryRepository(self.path) as repo, repo._transaction():
            state = repo._db.execute('SELECT * FROM video_cache_state WHERE channel_id = ?', (channel_id,)).fetchone()
            rows = repo._db.execute('SELECT * FROM video_stats WHERE channel_id = ? ORDER BY position, rowid', (channel_id,)).fetchall()
            videos = [_decode(row, VideoStats) for row in rows]
            if state:
                stamp = datetime.fromisoformat(state['fetched_at']) if state['fetched_at'] else None
                return VideoWindow(videos, stamp, state['requested_limit'], bool(state['complete']))
            stamp = min((v.fetched_at for v in videos if v.fetched_at is not None), default=None)
            return VideoWindow(videos, stamp, len(videos), False)
