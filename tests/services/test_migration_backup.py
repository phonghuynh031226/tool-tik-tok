"""Migration snapshots preserve the committed pre-upgrade database."""

import sqlite3

import pytest

from app.db import backup as backup_module
from app.db import migrations
from app.db.repository import SQLiteHistoryRepository


def make_legacy(path):
    db = sqlite3.connect(path, isolation_level=None)
    migrations._version_one(db)
    db.execute('CREATE TABLE schema_version(version INTEGER NOT NULL)')
    db.execute('INSERT INTO schema_version VALUES(1)')
    db.execute("INSERT INTO jobs(original_title,created_at) VALUES('Tiếng Việt cũ','2026-01-01')")
    return db


def test_pending_migration_creates_restorable_pre_upgrade_snapshot(tmp_path):
    path = tmp_path / 'custom.db'
    make_legacy(path).close()
    with SQLiteHistoryRepository(path) as repo:
        assert repo.get(1)['title'] == 'Tiếng Việt cũ'
    backups = list((tmp_path / 'backups').glob('custom.db.*.bak'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert backup.execute('SELECT version FROM schema_version').fetchone() == (1,)
        assert backup.execute('SELECT original_title FROM jobs').fetchone() == ('Tiếng Việt cũ',)
        assert 'scheduled_at' not in {row[1] for row in backup.execute('PRAGMA table_info(jobs)')}
    with SQLiteHistoryRepository(path):
        pass
    assert list((tmp_path / 'backups').glob('*.bak')) == backups


@pytest.mark.parametrize('existing_empty_file', [False, True])
def test_fresh_database_does_not_create_backup(tmp_path, existing_empty_file):
    path = tmp_path / 'fresh.db'
    if existing_empty_file:
        path.touch()
    with SQLiteHistoryRepository(path):
        pass
    assert not (tmp_path / 'backups').exists()


def test_backup_includes_committed_wal_rows(tmp_path):
    path = tmp_path / 'wal.db'
    source = make_legacy(path)
    try:
        source.execute('PRAGMA journal_mode=WAL')
        source.execute('PRAGMA wal_autocheckpoint=0')
        source.execute("INSERT INTO jobs(original_title,created_at) VALUES('WAL row','2026-01-02')")
        assert path.with_name(path.name + '-wal').stat().st_size > 0
        with SQLiteHistoryRepository(path):
            pass
        backups = list((tmp_path / 'backups').glob('*.bak'))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute('SELECT original_title FROM jobs ORDER BY id').fetchall() == [
                ('Tiếng Việt cũ',), ('WAL row',),
            ]
            assert backup.execute('SELECT version FROM schema_version').fetchone() == (1,)
    finally:
        source.close()


def test_backup_failure_aborts_before_schema_or_data_changes(tmp_path):
    path = tmp_path / 'unchanged.db'
    make_legacy(path).close()
    original = path.read_bytes()
    # A real filesystem failure: the required backup directory is a file.
    (tmp_path / 'backups').write_text('occupied', encoding='utf-8')
    with pytest.raises(migrations.MigrationError):
        SQLiteHistoryRepository(path)
    assert path.read_bytes() == original
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM schema_version').fetchone() == (1,)
        assert db.execute('SELECT original_title FROM jobs').fetchone() == ('Tiếng Việt cũ',)


def test_failed_upgrade_retains_pre_upgrade_backup(tmp_path, monkeypatch):
    path = tmp_path / 'failed.db'
    make_legacy(path).close()

    def fail(db):
        db.execute("UPDATE jobs SET original_title='changed'")
        raise RuntimeError('simulated upgrade failure')

    monkeypatch.setattr(migrations, '_version_two', fail)
    with pytest.raises(RuntimeError, match='simulated upgrade failure'):
        SQLiteHistoryRepository(path)
    backups = list((tmp_path / 'backups').glob('*.bak'))
    assert len(backups) == 1
    for database in (path, backups[0]):
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT version FROM schema_version').fetchone() == (1,)
            assert db.execute('SELECT original_title FROM jobs').fetchone() == ('Tiếng Việt cũ',)


def test_backup_api_failure_is_sanitized_and_removes_partial_file(tmp_path, monkeypatch):
    path = tmp_path / 'api_failure.db'
    make_legacy(path).close()
    original = path.read_bytes()
    connect = sqlite3.connect

    class FailingSource(sqlite3.Connection):
        def backup(self, target, **kwargs):
            raise sqlite3.OperationalError('sensitive-test-marker-do-not-expose')

    def failing_source_connect(database, *args, **kwargs):
        if kwargs.get('uri') and str(database).endswith('?mode=ro'):
            kwargs['factory'] = FailingSource
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(backup_module.sqlite3, 'connect', failing_source_connect)
    with pytest.raises(migrations.MigrationError) as error:
        SQLiteHistoryRepository(path)
    assert 'sensitive-test-marker' not in str(error.value)
    assert error.value.__suppress_context__
    assert not list((tmp_path / 'backups').glob('*.bak'))
    assert path.read_bytes() == original


def test_existing_backup_is_never_overwritten(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    path = tmp_path / 'collision.db'
    make_legacy(path).close()
    original = path.read_bytes()

    class FixedTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(backup_module, 'datetime', FixedTime)
    directory = tmp_path / 'backups'
    directory.mkdir()
    previous = directory / 'collision.db.20260102T030405000000Z.bak'
    previous.write_bytes(b'previous backup must survive')
    with pytest.raises(migrations.MigrationError):
        SQLiteHistoryRepository(path)
    assert previous.read_bytes() == b'previous backup must survive'
    assert path.read_bytes() == original
