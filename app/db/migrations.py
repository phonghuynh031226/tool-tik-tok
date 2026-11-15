"""Transactional SQLite schema migrations. No executescript implicit commits."""

from __future__ import annotations

import sqlite3
import re

from app.security.redaction import redact_text
from .backup import backup_before_migration

CURRENT_VERSION = 4


class MigrationError(RuntimeError):
    pass


def _version_one(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tiktok_url TEXT, tiktok_video_id TEXT, original_title TEXT, original_description TEXT,
        author TEXT, local_mp4_path TEXT, sha256 TEXT, duration REAL, resolution TEXT, file_size INTEGER,
        youtube_title TEXT, youtube_description TEXT, hashtags TEXT NOT NULL DEFAULT '[]',
        tags TEXT NOT NULL DEFAULT '[]', youtube_video_id TEXT, youtube_url TEXT, youtube_channel_id TEXT,
        privacy_status TEXT NOT NULL DEFAULT 'private' CHECK (privacy_status IN ('private','unlisted','public')),
        processing_status TEXT NOT NULL DEFAULT 'NEW'
            CHECK (processing_status IN ('NEW','METADATA_OK','DOWNLOADED','CONTENT_READY','UPLOADING','UPLOADED','FAILED','CANCELLED')),
        error_message TEXT, created_at TEXT NOT NULL, uploaded_at TEXT)''')


def _version_two(db: sqlite3.Connection) -> None:
    additions = (
        'made_for_kids INTEGER NOT NULL DEFAULT 0 CHECK (made_for_kids IN (0,1))',
        "category_id TEXT NOT NULL DEFAULT '22'", 'gemini_model TEXT', 'prompt_version TEXT',
        'rights_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (rights_confirmed IN (0,1))',
        'upload_session_uri TEXT',
        'retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0)',
        "extra_json TEXT NOT NULL DEFAULT '{}'",
    )
    for definition in additions:  # SQL identifiers/definitions are fixed program constants.
        db.execute('ALTER TABLE jobs ADD COLUMN ' + definition)
    db.execute('UPDATE jobs SET sha256 = lower(sha256) WHERE sha256 IS NOT NULL')
    db.execute('CREATE INDEX jobs_video_id_idx ON jobs(tiktok_video_id)')
    db.execute('CREATE INDEX jobs_sha256_idx ON jobs(sha256)')
    db.execute('CREATE INDEX jobs_status_idx ON jobs(processing_status)')
    # Retain legacy rows, including duplicates, while removing recognizable secrets.
    columns = ('tiktok_url', 'original_title', 'original_description', 'author', 'youtube_title',
               'youtube_description', 'youtube_url', 'error_message')
    for row in db.execute('SELECT id, ' + ', '.join(columns) + ' FROM jobs').fetchall():
        for index, column in enumerate(columns, 1):
            text = row[index]
            if isinstance(text, str) and (clean := redact_text(text)) != text:
                db.execute(f'UPDATE jobs SET {column} = ? WHERE id = ?', (clean, row[0]))


def _version_three(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
    for name in ('scheduled_at', 'channel_id'):
        if name not in columns:
            db.execute(f'ALTER TABLE jobs ADD COLUMN {name} TEXT')
    # Rebuild only the status CHECK; preserve legacy/custom columns and indexes.
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()[0]
    pattern = r'(CHECK\s*\(\s*processing_status\s+IN\s*\()([^)]*)(\)\s*\))'
    def extend(match):
        return match[0] if "'SCHEDULED'" in match[2] else match[1] + match[2] + ",'SCHEDULED'" + match[3]
    upgraded, count = re.subn(pattern, extend, sql, flags=re.IGNORECASE)
    if count > 1 or (count == 0 and re.search(r'CHECK\s*\(\s*processing_status', sql, re.IGNORECASE)):
        raise MigrationError('Không nhận diện được ràng buộc trạng thái; dữ liệu được giữ nguyên.')
    if upgraded != sql:
        objects = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='jobs' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='jobs'").fetchone()
        create = re.sub(r'CREATE\s+TABLE\s+(?:"jobs"|\[jobs\]|`jobs`|jobs)', 'CREATE TABLE jobs_v3', upgraded, count=1, flags=re.IGNORECASE)
        db.execute(create)
        names = ', '.join('"' + row[1].replace('"', '""') + '"' for row in db.execute('PRAGMA table_info(jobs)'))
        db.execute(f'INSERT INTO jobs_v3 ({names}) SELECT {names} FROM jobs')
        db.execute('DROP TABLE jobs')
        db.execute('ALTER TABLE jobs_v3 RENAME TO jobs')
        for row in objects:
            db.execute(row[0])
        if sequence:
            db.execute("UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name='jobs'", (sequence[0],))
            if not db.execute("SELECT 1 FROM sqlite_sequence WHERE name='jobs'").fetchone():
                db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('jobs',?)", (sequence[0],))
    db.execute('''CREATE TABLE IF NOT EXISTS channel_stats (
        channel_id TEXT PRIMARY KEY, subscribers INTEGER, total_views INTEGER NOT NULL DEFAULT 0,
        video_count INTEGER NOT NULL DEFAULT 0, subscribers_hidden INTEGER NOT NULL DEFAULT 0,
        fetched_at TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS video_stats (
        channel_id TEXT NOT NULL, video_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
        thumbnail_url TEXT, published_at TEXT, scheduled_at TEXT,
        privacy_status TEXT NOT NULL DEFAULT 'private', duration_seconds REAL NOT NULL DEFAULT 0,
        views INTEGER NOT NULL DEFAULT 0, likes INTEGER, comments INTEGER, fetched_at TEXT,
        PRIMARY KEY(channel_id, video_id))''')


def _version_four(db: sqlite3.Connection) -> None:
    if 'position' not in {row[1] for row in db.execute('PRAGMA table_info(video_stats)')}:
        db.execute('ALTER TABLE video_stats ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
    db.execute('''CREATE TABLE IF NOT EXISTS video_cache_state (
        channel_id TEXT PRIMARY KEY, fetched_at TEXT, requested_limit INTEGER NOT NULL,
        complete INTEGER NOT NULL DEFAULT 0)''')


def migrate(db: sqlite3.Connection) -> None:
    foreign_keys = db.execute('PRAGMA foreign_keys').fetchone()[0]
    db.execute('PRAGMA foreign_keys = OFF')
    db.execute('BEGIN IMMEDIATE')
    try:
        has_version = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
        versions = db.execute('SELECT version FROM schema_version').fetchall() if has_version else []
        if len(versions) > 1:
            raise MigrationError('Bảng phiên bản cơ sở dữ liệu không hợp lệ.')
        current = versions[0][0] if versions else 0
        if not isinstance(current, int) or current < 0 or current > CURRENT_VERSION:
            raise MigrationError('Cơ sở dữ liệu dùng phiên bản không được hỗ trợ; dữ liệu được giữ nguyên.')
        if current < CURRENT_VERSION and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            try:
                backup_before_migration(db)
            except Exception:
                raise MigrationError('Không thể sao lưu cơ sở dữ liệu; hủy nâng cấp và giữ nguyên dữ liệu.') from None
        db.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
        if not versions:
            db.execute('INSERT INTO schema_version(version) VALUES (?)', (0,))
        for number, upgrade in ((1, _version_one), (2, _version_two), (3, _version_three), (4, _version_four)):
            if current < number:
                upgrade(db)
                db.execute('UPDATE schema_version SET version = ?', (number,))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise MigrationError('Ràng buộc dữ liệu không hợp lệ; hủy nâng cấp.')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    finally:
        db.execute(f'PRAGMA foreign_keys = {int(foreign_keys)}')
