"""Transactional SQLite schema migrations. No executescript implicit commits."""

from __future__ import annotations

import sqlite3

from app.security.redaction import redact_text

CURRENT_VERSION = 2


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


def migrate(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
        versions = db.execute('SELECT version FROM schema_version').fetchall()
        if len(versions) > 1:
            raise MigrationError('Bảng phiên bản cơ sở dữ liệu không hợp lệ.')
        current = versions[0][0] if versions else 0
        if not isinstance(current, int) or current < 0 or current > CURRENT_VERSION:
            raise MigrationError('Cơ sở dữ liệu dùng phiên bản không được hỗ trợ; dữ liệu được giữ nguyên.')
        if not versions:
            db.execute('INSERT INTO schema_version(version) VALUES (?)', (0,))
        for number, upgrade in ((1, _version_one), (2, _version_two)):
            if current < number:
                upgrade(db)
                db.execute('UPDATE schema_version SET version = ?', (number,))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
