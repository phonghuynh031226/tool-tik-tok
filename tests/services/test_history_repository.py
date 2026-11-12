import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from app.contracts import HistoryRepository, JobStatus
from app.db.repository import DuplicateJobError, SQLiteHistoryRepository
from app.db.migrations import CURRENT_VERSION


@pytest.fixture
def repo(tmp_path):
    with SQLiteHistoryRepository(tmp_path / 'app.db') as repository:
        yield repository


def test_crud_aliases_unicode_and_detached_results(repo):
    assert isinstance(repo, HistoryRepository)
    job_id = repo.add({'video_id': '123', 'url': 'https://www.tiktok.com/@a/video/123',
                       'title': 'Tiếng Việt 🐈', 'description': 'Mô tả', 'author': 'Tác giả',
                       'status': JobStatus.NEW, 'tags': ['mèo', 'Việt Nam'], 'custom_data': {'items': [1]}})
    job = repo.get(job_id)
    assert job['tiktok_video_id'] == job['video_id'] == '123'
    assert job['original_title'] == job['title'] == 'Tiếng Việt 🐈'
    assert job['processing_status'] == job['status'] == JobStatus.NEW
    assert job['privacy_status'] == 'private' and job['rights_confirmed'] is False
    assert job['created_at'] and job['uploaded_at'] is None
    job['tags'].append('changed')
    job['custom_data']['items'].append(2)
    assert repo.get(job_id)['tags'] == ['mèo', 'Việt Nam']
    assert repo.get(job_id)['custom_data'] == {'items': [1]}
    repo.update(job_id, {'id': 999, 'status': JobStatus.UPLOADED, 'youtube_title': 'Đã đăng', 'rights_confirmed': True})
    assert repo.get(job_id)['id'] == job_id
    assert repo.get(job_id)['uploaded_at']
    assert repo.get(job_id)['rights_confirmed'] is True
    repo.delete(job_id)
    assert repo.get(job_id) is None and repo.list() == []
    with pytest.raises(KeyError):
        repo.update(job_id, {})


def test_all_requested_columns_exist(repo):
    expected = '''id tiktok_url tiktok_video_id original_title original_description author local_mp4_path sha256 duration
        resolution file_size youtube_title youtube_description hashtags tags youtube_video_id youtube_url youtube_channel_id
        privacy_status made_for_kids category_id gemini_model prompt_version rights_confirmed upload_session_uri
        processing_status error_message retry_count created_at uploaded_at'''.split()
    with sqlite3.connect(repo.path) as db:
        assert set(expected) <= {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
        assert db.execute('SELECT version FROM schema_version').fetchall() == [(CURRENT_VERSION,)]
        assert db.execute('PRAGMA encoding').fetchone()[0] == 'UTF-8'


def test_list_search_filters_unicode_literal_wildcards_and_pagination(repo):
    first = repo.add({'video_id': '1', 'title': 'TIẾNG VIỆT %_ literal'})
    second = repo.add({'video_id': '2', 'title': 'Other', 'status': JobStatus.FAILED})
    assert [job['id'] for job in repo.list()] == [second, first]
    assert repo.list(limit=1, offset=1)[0]['id'] == first
    assert repo.list(status=JobStatus.FAILED)[0]['id'] == second
    assert repo.search('tiếng việt')[0]['id'] == first
    assert repo.search('%_')[0]['id'] == first
    assert repo.search('not here') == [] and repo.list(limit=0) == []
    with pytest.raises(ValueError):
        repo.list(limit=-1)
    with pytest.raises(ValueError):
        repo.search('x', offset=-1)


def test_duplicate_video_and_hash_detected_on_add_and_update(repo):
    digest = hashlib.sha256(b'video').hexdigest()
    first = repo.add({'video_id': '1', 'sha256': digest})
    for record in [{'video_id': '1'}, {'video_id': 'different', 'sha256': digest.upper()}]:
        with pytest.raises(DuplicateJobError) as caught:
            repo.add(record)
        assert caught.value.existing_ids == (first,)
    second = repo.add({'video_id': '2'})
    with pytest.raises(DuplicateJobError):
        repo.update(second, {'sha256': digest})
    assert repo.get(second)['sha256'] is None
    repo.update(first, {'sha256': digest})  # Updating the same job is allowed.
    assert repo.find_by_video_id('1')['id'] == first
    assert repo.find_by_hash(digest.upper())['id'] == first
    assert repo.find_by_hash('missing') is None


def test_duplicate_check_is_atomic_across_connections(tmp_path):
    path = tmp_path / 'app.db'
    with SQLiteHistoryRepository(path) as left, SQLiteHistoryRepository(path) as right:
        def insert(repository):
            try:
                return repository.add({'video_id': 'same'})
            except DuplicateJobError:
                return 'duplicate'
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(insert, [left, right]))
        assert result.count('duplicate') == 1
        assert len(left.list()) == 1


def test_sql_injection_in_values_keys_and_search_is_data(repo):
    payload = "x'); DROP TABLE jobs; --"
    job_id = repo.add({'video_id': payload, 'title': payload, payload: 'extra'})
    assert repo.find_by_video_id(payload)['id'] == job_id
    assert repo.search(payload)[0]['id'] == job_id
    assert repo.search("' OR 1=1 --") == []
    repo.update(job_id, {'youtube_description': payload})
    assert repo.get(job_id)['youtube_description'] == payload
    assert len(repo.list()) == 1


@pytest.mark.parametrize('changes', [{'status': 'NOT_A_STATUS'}, {'retry_count': -1}, {'made_for_kids': 'false'},
    {'privacy_status': 'everyone'}, {'tags': 'not-a-list'}, {'sha256': 'not-a-hash'}])
def test_invalid_data_does_not_write(repo, changes):
    with pytest.raises((ValueError, TypeError)):
        repo.add(changes)
    assert repo.list() == []


def test_migrate_v1_database_preserves_data_and_legacy_duplicates(tmp_path):
    path = tmp_path / 'old.db'
    digest = hashlib.sha256(b'legacy-video').hexdigest()
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
        db.execute('INSERT INTO schema_version VALUES (1)')
        db.execute('''CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, tiktok_url TEXT, tiktok_video_id TEXT, original_title TEXT,
            original_description TEXT, author TEXT, local_mp4_path TEXT, sha256 TEXT, duration REAL,
            resolution TEXT, file_size INTEGER, youtube_title TEXT, youtube_description TEXT,
            hashtags TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]', youtube_video_id TEXT,
            youtube_url TEXT, youtube_channel_id TEXT, privacy_status TEXT NOT NULL DEFAULT 'private',
            processing_status TEXT NOT NULL DEFAULT 'NEW', error_message TEXT,
            created_at TEXT NOT NULL, uploaded_at TEXT)''')
        for title in ['Cũ tiếng Việt', 'Bản ghi sau']:
            db.execute('INSERT INTO jobs (tiktok_video_id, original_title, sha256, created_at) VALUES (?, ?, ?, ?)',
                       ('legacy', title, digest.upper(), '2026-11-12T00:00:00+00:00'))
    with SQLiteHistoryRepository(path) as migrated:
        assert len(migrated.list()) == 2
        assert migrated.get(1)['title'] == 'Cũ tiếng Việt'
        assert migrated.find_by_video_id('legacy')['title'] == 'Bản ghi sau'
        assert migrated.get(1)['rights_confirmed'] is False
        assert migrated.get(1)['retry_count'] == 0
        assert migrated.find_by_hash(digest)['id'] == 2
        with pytest.raises(DuplicateJobError):
            migrated.add({'video_id': 'legacy'})
        with pytest.raises(DuplicateJobError):
            migrated.add({'video_id': 'new-id', 'sha256': digest})
    with SQLiteHistoryRepository(path) as reopened:
        assert len(reopened.list()) == 2  # Idempotent migrations.


def test_future_schema_rejected_without_modification(tmp_path):
    path = tmp_path / 'future.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
        db.execute('INSERT INTO schema_version VALUES (999)')
    with pytest.raises(Exception, match='phiên bản'):
        SQLiteHistoryRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 999


def test_csv_exports_all_rows_unicode_and_escapes_formula(repo, tmp_path):
    for index in range(105):
        repo.add({'video_id': str(index), 'title': 'Tiếng Việt' if index else '=1+1'})
    destination = tmp_path / 'history.csv'
    assert repo.export_csv(destination) == destination
    with destination.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 105 and rows[0]['original_title'] == 'Tiếng Việt'
    assert rows[-1]['original_title'] == "'=1+1"


def test_sensitive_fields_rejected_and_error_text_redacted(repo):
    for record in [{'api_key': 'dummy'}, {'extra': {'refresh_token': 'dummy'}}, {'youtube_token': 'dummy'}]:
        with pytest.raises(ValueError):
            repo.add(record)
    job_id = repo.add({'error_message': 'access_token=dummy-sensitive-value'})
    assert 'dummy-sensitive-value' not in repo.get(job_id)['error_message']
    with sqlite3.connect(repo.path) as db:
        assert 'dummy-sensitive-value' not in str(db.execute('SELECT * FROM jobs').fetchall())


def test_legacy_duplicates_can_still_update_status_without_new_identity(repo):
    first = repo.add({'video_id': 'legacy'})
    with sqlite3.connect(repo.path) as db:
        db.execute('INSERT INTO jobs (tiktok_video_id, created_at) VALUES (?, ?)', ('legacy', '2026-11-12'))
    repo.update(first, {'status': JobStatus.FAILED, 'error_message': 'Lỗi tạm thời'})
    assert repo.get(first)['status'] == JobStatus.FAILED
    repo.update(first, {'video_id': 'legacy', 'title': 'Có thể sửa'})
    assert repo.get(first)['title'] == 'Có thể sửa'


def test_upload_session_uri_is_only_in_secret_store(tmp_path):
    values = {}
    secrets = Mock()
    secrets.set.side_effect = lambda key, value: values.__setitem__(key, value)
    secrets.get.side_effect = values.get
    secrets.delete.side_effect = lambda key: values.pop(key, None)
    session = 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=dummy-resumable-secret'
    path = tmp_path / 'app.db'
    with SQLiteHistoryRepository(path, secret_store=secrets) as repo:
        job_id = repo.add({'video_id': '1', 'upload_session_uri': session})
        reference = repo.get(job_id)['upload_session_uri']
        assert reference.startswith('keyring:upload-session:') and reference != session
        assert repo.get_upload_session_uri(job_id) == session
        assert session not in str(repo.list())
        exported = repo.export_csv(tmp_path / 'history.csv')
        assert 'dummy-resumable-secret' not in exported.read_text(encoding='utf-8-sig')
        repo.update(job_id, {'upload_session_uri': None})
        assert values == {} and repo.get_upload_session_uri(job_id) is None
    for stored in tmp_path.glob('app.db*'):
        assert b'dummy-resumable-secret' not in stored.read_bytes()
