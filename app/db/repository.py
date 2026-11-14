"""SQLite history with frozen protocol aliases and credential-free persistence.

Default database: data/app.db. CRUD/storage/export paths are project-local.
New duplicate video ids/hashes raise DuplicateJobError; no history is overwritten.
Legacy duplicates remain queryable, newest first. Extra nonsecret JSON fields are
supported. Resumable upload credentials live only in SecretStore; DB holds an opaque
reference. Resolve them explicitly with get_upload_session_uri(), never CSV export.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from threading import RLock
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from app.contracts import HistoryRecord, JobStatus, SecretStore
from app.core.paths import safe_path
from app.security.redaction import REDACTED, is_sensitive_key, nonsecret_value, redact_text
from app.security.secrets import KeyringSecretStore
from .migrations import migrate

JOB_COLUMNS = tuple('''id tiktok_url tiktok_video_id original_title original_description author local_mp4_path
    sha256 duration resolution file_size youtube_title youtube_description hashtags tags youtube_video_id
    youtube_url youtube_channel_id privacy_status made_for_kids category_id gemini_model prompt_version
    rights_confirmed upload_session_uri processing_status error_message retry_count created_at uploaded_at
    scheduled_at channel_id'''.split())
_ALIASES = {'video_id': 'tiktok_video_id', 'url': 'tiktok_url', 'title': 'original_title',
            'description': 'original_description', 'status': 'processing_status'}
_BOOLS = {'made_for_kids', 'rights_confirmed'}
_LISTS = {'hashtags', 'tags'}
_SESSION_REFERENCE = re.compile(r'^keyring:upload-session:([a-f0-9]{32})$')
_MISSING = object()


class DuplicateJobError(ValueError):
    def __init__(self, existing_ids: tuple[int, ...]):
        super().__init__('Video hoặc SHA-256 đã có trong lịch sử.')
        self.existing_ids = existing_ids


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class SQLiteHistoryRepository:
    def __init__(self, path: Path | None = None, *, secret_store: SecretStore | None = None) -> None:
        self.path = safe_path(path if path is not None else Path('data/app.db'))
        for suffix in ('-wal', '-shm', '-journal'):
            safe_path(Path(str(self.path) + suffix))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._secret_store = secret_store
        self._db = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute('PRAGMA encoding = "UTF-8"')
            if self._db.execute('PRAGMA encoding').fetchone()[0] != 'UTF-8':
                raise ValueError('Cơ sở dữ liệu phải dùng UTF-8.')
            self._db.execute('PRAGMA foreign_keys = ON')
            self._db.execute('PRAGMA temp_store = MEMORY')
            self._db.execute('PRAGMA busy_timeout = 5000')
            self._db.create_function('casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            migrate(self._db)
        except BaseException:
            self._db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise

    def _normalize(self, record: Mapping[str, Any]) -> tuple[dict, dict, Any]:
        if not isinstance(record, Mapping):
            raise TypeError('Bản ghi lịch sử phải là Mapping.')
        values, extras = {}, {}
        session = _MISSING
        for original, value in record.items():
            if not isinstance(original, str):
                raise TypeError('Tên trường phải là chuỗi.')
            key = _ALIASES.get(original, original)
            if key == 'id':
                continue  # Preserve generated primary key on add/update.
            if key == 'upload_session_uri':
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError('URI phiên tải lên không hợp lệ.')
                    parsed = urlsplit(value)
                    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                        raise ValueError('URI phiên tải lên phải là HTTPS hợp lệ.')
                session = value
                continue
            if key == 'extra_json' or is_sensitive_key(key):
                raise ValueError('Thông tin bí mật hoặc trường nội bộ không được lưu vào lịch sử.')
            if isinstance(value, Path):
                value = str(value)
            if key == 'scheduled_at' and value is not None:
                stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
                if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError('Thời điểm hẹn phải có múi giờ.')
                value = stamp.isoformat()
            value = nonsecret_value(value)
            if key not in JOB_COLUMNS:
                extras[key] = value
                continue
            if key == 'processing_status':
                value = JobStatus(value).value
            elif key in _BOOLS:
                if not isinstance(value, bool):
                    raise ValueError('Giá trị xác nhận phải là boolean.')
                value = int(value)
            elif key in _LISTS:
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError('Tags và hashtags phải là danh sách chuỗi.')
                value = _json(value)
            elif key in {'retry_count', 'file_size'}:
                if value is None and key == 'file_size':
                    pass
                elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError('Số lần thử/kích thước phải là số nguyên không âm.')
            elif key == 'duration':
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                    raise ValueError('Thời lượng không hợp lệ.')
            elif key == 'sha256':
                if value in (None, ''):
                    value = None
                elif not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value):
                    raise ValueError('SHA-256 không hợp lệ.')
                else:
                    value = value.lower()
            elif key == 'privacy_status':
                if value not in {'private', 'unlisted', 'public'}:
                    raise ValueError('Quyền riêng tư không hợp lệ.')
            elif value is not None and not isinstance(value, str):
                raise ValueError('Giá trị trường văn bản không hợp lệ.')
            if key == 'tiktok_video_id' and value == '':
                value = None
            if key in values and values[key] != value:
                raise ValueError('Giá trị alias và cột chính không khớp.')
            values[key] = value
        _json(extras)  # Reject unsupported/non-finite nested JSON before a transaction.
        return values, extras, session

    def _check_duplicate(self, video_id, sha256, *, excluding_id: int | None = None) -> None:
        rows = self._db.execute('''SELECT id FROM jobs WHERE (tiktok_video_id = ? OR sha256 = ?)
            AND (? IS NULL OR id != ?) ORDER BY id DESC''', (video_id, sha256, excluding_id, excluding_id)).fetchall()
        if rows:
            raise DuplicateJobError(tuple(row[0] for row in rows))

    def _secrets(self) -> SecretStore:
        if self._secret_store is None:
            self._secret_store = KeyringSecretStore()
        return self._secret_store

    @staticmethod
    def _session_key(reference: str) -> str:
        match = _SESSION_REFERENCE.fullmatch(reference)
        if not match:
            raise ValueError('Tham chiếu phiên tải lên không hợp lệ.')
        return 'upload-session:' + match[1]

    def _new_session(self, session: str | None) -> str | None:
        if session is None:
            return None
        key = 'upload-session:' + uuid4().hex
        self._secrets().set(key, session)
        return 'keyring:' + key

    def _delete_session(self, reference: str | None) -> None:
        if reference:
            self._secrets().delete(self._session_key(reference))

    def add(self, record: Mapping[str, Any]) -> int:
        values, extras, session = self._normalize(record)
        values.setdefault('created_at', _utc_now())
        if values.get('processing_status') == JobStatus.UPLOADED.value:
            values.setdefault('uploaded_at', _utc_now())
        values['extra_json'] = _json(extras)
        new_reference = None
        try:
            with self._transaction():
                self._check_duplicate(values.get('tiktok_video_id'), values.get('sha256'))
                if session is not _MISSING:
                    new_reference = self._new_session(session)
                    values['upload_session_uri'] = new_reference
                # Keys originate solely from the fixed schema, never user identifiers.
                columns = ', '.join(values)
                placeholders = ', '.join('?' for _ in values)
                cursor = self._db.execute(f'INSERT INTO jobs ({columns}) VALUES ({placeholders})', tuple(values.values()))
                job_id = cursor.lastrowid
            return job_id
        except BaseException:
            if new_reference:
                self._delete_session(new_reference)
            raise

    def update(self, job_id: int, changes: Mapping[str, Any]) -> None:
        values, extras, session = self._normalize(changes)
        new_reference, old_reference = None, None
        try:
            with self._transaction():
                old = self._db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
                if old is None:
                    raise KeyError(job_id)
                # Legacy duplicates may still change status/content. Reject only
                # identifier changes that would introduce a new collision.
                self._check_duplicate(
                    values.get('tiktok_video_id') if values.get('tiktok_video_id', old['tiktok_video_id']) != old['tiktok_video_id'] else None,
                    values.get('sha256') if values.get('sha256', old['sha256']) != old['sha256'] else None,
                    excluding_id=job_id,
                )
                if extras:
                    values['extra_json'] = _json(json.loads(old['extra_json']) | extras)
                if values.get('processing_status') == JobStatus.UPLOADED.value and not old['uploaded_at']:
                    values.setdefault('uploaded_at', _utc_now())
                if session is not _MISSING:
                    old_reference = old['upload_session_uri']
                    new_reference = self._new_session(session)
                    values['upload_session_uri'] = new_reference
                if values:
                    assignments = ', '.join(f'{key} = ?' for key in values)
                    self._db.execute(f'UPDATE jobs SET {assignments} WHERE id = ?', (*values.values(), job_id))
        except BaseException:
            if new_reference:
                self._delete_session(new_reference)
            raise
        if old_reference:
            self._delete_session(old_reference)

    @staticmethod
    def _decode(row: sqlite3.Row) -> HistoryRecord:
        record = dict(row)
        extras = json.loads(record.pop('extra_json'))
        record = extras | record
        for field in _LISTS:
            record[field] = json.loads(record[field])
        for field in _BOOLS:
            record[field] = bool(record[field])
        record['processing_status'] = JobStatus(record['processing_status'])
        for alias, field in _ALIASES.items():
            record[alias] = record[field]
        return record

    def get(self, job_id: int) -> HistoryRecord | None:
        with self._lock:
            row = self._db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
            return self._decode(row) if row is not None else None

    def delete(self, job_id: int) -> None:
        reference = None
        with self._transaction():
            row = self._db.execute('SELECT upload_session_uri FROM jobs WHERE id = ?', (job_id,)).fetchone()
            if row is not None:
                reference = row[0]
                self._db.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
        self._delete_session(reference)

    def get_upload_session_uri(self, job_id: int) -> str | None:
        with self._lock:
            row = self._db.execute('SELECT upload_session_uri FROM jobs WHERE id = ?', (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self._secrets().get(self._session_key(row[0])) if row[0] else None

    def find_by_video_id(self, video_id: str) -> HistoryRecord | None:
        with self._lock:
            row = self._db.execute('SELECT * FROM jobs WHERE tiktok_video_id = ? ORDER BY id DESC LIMIT 1', (video_id,)).fetchone()
            return self._decode(row) if row is not None else None

    def find_by_hash(self, sha256: str) -> HistoryRecord | None:
        with self._lock:
            row = self._db.execute('SELECT * FROM jobs WHERE sha256 = ? ORDER BY id DESC LIMIT 1', (sha256.lower(),)).fetchone()
            return self._decode(row) if row is not None else None

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (limit, offset)):
            raise ValueError('limit và offset phải là số nguyên không âm.')

    def search(self, query: str, limit: int = 100, offset: int = 0) -> list[HistoryRecord]:
        self._validate_page(limit, offset)
        with self._lock:
            rows = self._db.execute('''SELECT * FROM jobs WHERE instr(casefold(tiktok_video_id), casefold(?)) > 0
                OR instr(casefold(original_title), casefold(?)) > 0 OR instr(casefold(tiktok_url), casefold(?)) > 0
                OR instr(casefold(youtube_title), casefold(?)) > 0 ORDER BY id DESC LIMIT ? OFFSET ?''',
                (query, query, query, query, limit, offset)).fetchall()
            return [self._decode(row) for row in rows]

    def list(self, limit: int = 100, offset: int = 0, status: JobStatus | None = None) -> list[HistoryRecord]:
        self._validate_page(limit, offset)
        filter_status = JobStatus(status).value if status is not None else None
        with self._lock:
            rows = self._db.execute('''SELECT * FROM jobs WHERE (? IS NULL OR processing_status = ?)
                ORDER BY id DESC LIMIT ? OFFSET ?''', (filter_status, filter_status, limit, offset)).fetchall()
            return [self._decode(row) for row in rows]

    def list_scheduled(self) -> list[HistoryRecord]:
        with self._lock:
            rows = self._db.execute('SELECT * FROM jobs WHERE processing_status = ? ORDER BY id DESC',
                                    (JobStatus.SCHEDULED.value,)).fetchall()
            return [self._decode(row) for row in rows]

    def export_csv(self, path: Path | None = None) -> Path:
        destination = safe_path(path if path is not None else Path('data/history.csv'))
        # Never overwrite the live SQLite database or its sidecars via CSV export.
        if destination == self.path or str(destination).startswith(str(self.path) + '-'):
            raise ValueError('Không được xuất CSV đè lên cơ sở dữ liệu.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            rows = self._db.execute('SELECT * FROM jobs ORDER BY id DESC').fetchall()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='', suffix='.tmp',
                                             dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
                writer = csv.writer(stream)
                columns = (*JOB_COLUMNS, 'extra_json')
                writer.writerow(columns)
                for row in rows:
                    values = []
                    for column in columns:
                        value = row[column]
                        if column == 'upload_session_uri' and value:
                            value = REDACTED
                        if isinstance(value, str):
                            value = redact_text(value)
                            if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                                value = "'" + value
                        values.append(value)
                    writer.writerow(values)
                stream.flush()
                os.fsync(stream.fileno())
            safe_path(temporary).replace(safe_path(destination))
        finally:
            if temporary is not None and temporary.exists():
                safe_path(temporary).unlink()
        return destination
