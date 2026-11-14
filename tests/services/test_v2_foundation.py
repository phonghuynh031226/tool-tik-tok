from dataclasses import fields, MISSING
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from app.contracts import (ChannelAccount, ChannelStats, VideoStats, UploadRequest,
    UploadResult, JobStatus, StatsCache, YouTubeService, HistoryRepository)
from app.errors import AccountNotFound, ScheduleInPast, AuthExpired, StatsUnavailable, ContentInvalid, Cancelled
from app.core.cancel import CancelToken
from app.services.fakes import FakeYouTubeService, FakeHistoryRepository, FakeStatsCache
from app.db.repository import SQLiteHistoryRepository
from app.db.migrations import migrate, CURRENT_VERSION, _version_one, _version_two


def test_legacy_constructors_and_new_defaults():
    req = UploadRequest(Path('sample.mp4'), 'Title', 'Desc', [])
    assert req.publish_at is None and req.channel_id is None
    assert UploadResult('id', 'url', 'channel').status == JobStatus.UPLOADED
    assert ChannelAccount().status == 'connected'
    assert ChannelStats().fetched_at is None
    assert VideoStats().likes is None and VideoStats().comments is None
    assert JobStatus('SCHEDULED') is JobStatus.SCHEDULED
    for model in (ChannelAccount, ChannelStats, VideoStats):
        assert all(field.default is not MISSING or field.default_factory is not MISSING for field in fields(model))
    for error_type in (AccountNotFound, ScheduleInPast, StatsUnavailable):
        error = error_type('internal detail')
        assert error.user_message and error.user_message != 'internal detail'


def test_fake_accounts_stats_and_hidden_metrics():
    service = FakeYouTubeService()
    assert isinstance(service, YouTubeService)
    accounts = service.list_accounts()
    assert len(accounts) == 3 and sum(account.is_default for account in accounts) == 1
    assert sum(account.status == 'expired' for account in accounts) == 1
    account = next(account for account in accounts if account.is_default)
    stats = service.get_channel_stats(account.id)
    assert stats.channel_id == account.id and stats.total_views > stats.video_count
    videos = service.list_channel_videos(account.id)
    assert len(videos) == 15 and any(video.likes is None for video in videos)
    assert len({video.views for video in videos}) > 1
    videos[0].title = 'Mutated'
    assert service.list_channel_videos(account.id)[0].title != 'Mutated'
    second = next(account for account in accounts if not account.is_default and account.status == 'connected')
    service.set_default_account(second.id)
    assert service.connect().id == second.id
    added = service.add_account()
    assert added.status == 'connected'
    service.remove_account(added.id)
    with pytest.raises(AccountNotFound): service.set_default_account('missing')
    expired = next(account for account in accounts if account.status == 'expired')
    with pytest.raises(AuthExpired): service.get_channel_stats(expired.id)


def test_fake_scheduling_and_explicit_channel():
    service = FakeYouTubeService()
    service.connect()
    account = service.list_accounts()[1]
    req = UploadRequest(Path('sample.mp4'), 'Title', 'Desc', [], rights_confirmed=True,
        publish_at=datetime.now(timezone.utc) + timedelta(days=1), channel_id=account.id)
    progress = []
    result = service.upload(req, progress.append, CancelToken())
    assert result.status == JobStatus.SCHEDULED and result.channel_id == account.id
    assert progress == [0.0, 0.5, 1.0]
    assert service.sync_scheduled() == []
    service._scheduled[result.video_id] = (datetime.now(timezone.utc) - timedelta(seconds=1), account.id)
    assert service.sync_scheduled()[0].status == JobStatus.UPLOADED
    assert service.sync_scheduled() == []
    req.publish_at = datetime.now(timezone.utc) - timedelta(days=1)
    with pytest.raises(ScheduleInPast): service.upload(req, progress.append, CancelToken())


def test_fake_schedule_requires_timezone_private_and_cancellation():
    service = FakeYouTubeService()
    service.connect()
    req = UploadRequest(Path('sample.mp4'), 'Title', 'Desc', [], rights_confirmed=True,
                        publish_at=datetime(2099, 1, 1))
    with pytest.raises(ContentInvalid):
        service.upload(req, lambda _: None, CancelToken())
    req.publish_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    req.privacy = 'public'
    with pytest.raises(ContentInvalid):
        service.upload(req, lambda _: None, CancelToken())
    req.privacy = 'private'
    token = CancelToken()
    with pytest.raises(Cancelled):
        service.upload(req, lambda _: token.cancel(), token)
    assert not service._scheduled


def test_fake_stats_cache_and_scheduled_history():
    cache = FakeStatsCache()
    assert isinstance(cache, StatsCache)
    stats = ChannelStats(channel_id='one', subscribers=12)
    cache.save_channel_stats(stats)
    assert cache.load_channel_stats('one') == stats
    cache.save_videos('one', [VideoStats(video_id='video', title='Title')])
    assert cache.load_videos('one')[0].video_id == 'video'
    assert cache.load_channel_stats('missing') is None and cache.load_videos('missing') == []
    history = FakeHistoryRepository()
    assert isinstance(history, HistoryRepository)
    job_id = history.add({'status': JobStatus.SCHEDULED})
    assert history.list_scheduled()[0]['id'] == job_id


def make_v2(path, *, partial=False):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
    db.execute('INSERT INTO schema_version VALUES (2)')
    _version_one(db)
    _version_two(db)
    db.execute('INSERT INTO jobs(id,original_title,created_at) VALUES(?,?,?)', (7, 'Tiếng Việt cũ', '2026-01-01'))
    db.execute('INSERT INTO jobs(id,created_at) VALUES(?,?)', (99, '2026-01-01'))
    db.execute('DELETE FROM jobs WHERE id = ?', (99,))
    if partial:
        db.execute('ALTER TABLE jobs ADD COLUMN scheduled_at TEXT')
        db.execute('ALTER TABLE jobs ADD COLUMN channel_id TEXT')
    db.close()


@pytest.mark.parametrize('partial', [False, True])
def test_migration_retains_data_and_supports_scheduled(tmp_path, partial):
    path = tmp_path / 'studio.db'
    make_v2(path, partial=partial)
    with SQLiteHistoryRepository(path) as repo:
        assert repo.get(7)['title'] == 'Tiếng Việt cũ'
        job_id = repo.add({'status': JobStatus.SCHEDULED, 'scheduled_at': datetime.now(timezone.utc) + timedelta(days=1), 'channel_id': 'channel-two'})
        assert job_id > 99
        assert repo.list_scheduled()[0]['channel_id'] == 'channel-two'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == CURRENT_VERSION
        assert {'channel_stats', 'video_stats'} <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    with SQLiteHistoryRepository(path) as repo:
        assert len(repo.list()) == 2


def test_migration_preserves_custom_columns_foreign_keys_indexes_and_triggers(tmp_path):
    path = tmp_path / 'studio.db'
    make_v2(path)
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE jobs ADD COLUMN custom_note TEXT')
        db.execute('UPDATE jobs SET custom_note = ? WHERE id = 7', ('Giữ nguyên',))
        db.execute('CREATE INDEX custom_note_idx ON jobs(custom_note)')
        db.execute('CREATE TABLE child(job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE)')
        db.execute('INSERT INTO child VALUES(7)')
        db.execute('CREATE TABLE audit(job_id INTEGER)')
        db.execute('CREATE TRIGGER jobs_audit AFTER UPDATE ON jobs BEGIN INSERT INTO audit VALUES(new.id); END')
    with SQLiteHistoryRepository(path) as repo:
        repo.update(7, {'status': JobStatus.SCHEDULED})
        assert repo._db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT custom_note FROM jobs WHERE id=7').fetchone()[0] == 'Giữ nguyên'
        assert db.execute('SELECT * FROM child').fetchall() == [(7,)]
        assert db.execute('SELECT * FROM audit').fetchall() == [(7,)]
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='custom_note_idx'").fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_failed_migration_rolls_back_all_schema_and_data(tmp_path, monkeypatch):
    from app.db import migrations
    path = tmp_path / 'studio.db'
    make_v2(path)
    upgrade = migrations._version_three
    def fail_after_upgrade(db):
        upgrade(db)
        raise RuntimeError('simulated migration failure')
    monkeypatch.setattr(migrations, '_version_three', fail_after_upgrade)
    with pytest.raises(RuntimeError, match='simulated'):
        SQLiteHistoryRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 2
        assert db.execute('SELECT id,original_title FROM jobs').fetchall() == [(7, 'Tiếng Việt cũ')]
        assert 'scheduled_at' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='jobs'").fetchone()[0] == 99
