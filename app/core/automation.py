"""Project-local automation reservations with 15-minute scheduling lead time.

The lead time includes a five-minute processing budget above YouTube validation.
Upload callers must revalidate the remaining schedule window before sending.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from app.core.paths import safe_path
from app.security.redaction import nonsecret_value

LOCAL_TZ = timezone(timedelta(hours=7), 'UTC+7')
_LIVE_LOCK = threading.RLock()
_LIVE_STORES: dict[str, int] = {}
_STATUSES = {'downloading', 'generating', 'uploading', 'done', 'failed', 'cancelled', 'uncertain'}


class RetryConfirmationRequired(ValueError):
    def __init__(self, job_id):
        self.job_id = job_id
        super().__init__('Lần trước bị ngắt nên chưa rõ kết quả; cần xác nhận chưa đăng trước khi thử lại.')


@dataclass(frozen=True)
class AutomationPolicy:
    privacy: str = 'private'
    made_for_kids: bool = False
    interval_minutes: int | None = None
    start_hour: int = 0
    start_minute: int = 0
    content_instructions: str = ''

    def __post_init__(self):
        if type(self.privacy) is not str or self.privacy not in {'private', 'public', 'unlisted'}:
            raise ValueError('Chế độ riêng tư không hợp lệ.')
        if type(self.made_for_kids) is not bool:
            raise ValueError('Phải chọn rõ nội dung dành cho trẻ em hay không.')
        if self.interval_minutes is not None and (type(self.interval_minutes) is not int or not 1 <= self.interval_minutes <= 1440):
            raise ValueError('Khoảng cách lịch phải từ 1 đến 1440 phút.')
        if type(self.start_hour) is not int or not 0 <= self.start_hour <= 23:
            raise ValueError('Giờ bắt đầu phải từ 00 đến 23.')
        if type(self.start_minute) is not int or not 0 <= self.start_minute <= 59:
            raise ValueError('Phút bắt đầu phải từ 00 đến 59.')
        if type(self.content_instructions) is not str or len(self.content_instructions) > 20000:
            raise ValueError('Chỉ dẫn nội dung không hợp lệ hoặc quá dài.')
        nonsecret_value(self.content_instructions, reject_text=True)
        if self.interval_minutes is not None:
            object.__setattr__(self, 'privacy', 'private')

    def summary(self) -> str:
        audience = 'dành cho trẻ em' if self.made_for_kids else 'không dành cho trẻ em'
        if self.interval_minutes is not None:
            action = (f'Tải lên riêng tư, hẹn công khai mỗi {self.interval_minutes} phút '
                      f'từ {self.start_hour:02d}:{self.start_minute:02d} (UTC+7), chừa ít nhất 15 phút xử lý')
        else:
            action = 'Đăng ngay: ' + {'private': 'riêng tư', 'public': 'công khai', 'unlisted': 'không công khai'}[self.privacy]
        return f'{action}; {audience}. Tải TikTok → tạo nội dung AI → tải lên YouTube.'


def _canonical_url(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError('Thiếu liên kết nguồn.')
    value = value.strip()
    nonsecret_value(value, reject_text=True)
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme not in {'https', 'http'} or not host or parts.username or parts.password:
        raise ValueError('Liên kết nguồn không hợp lệ.')
    if host != 'tiktok.com' and not host.endswith('.tiktok.com'):
        raise ValueError('Chỉ hỗ trợ liên kết TikTok.')
    video = re.search(r'/video/(\d+)', parts.path)
    if video:
        return 'https://www.tiktok.com/video/' + video.group(1)
    return urlunsplit(('https', host, parts.path.rstrip('/'), '', ''))


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied: conservatively leave it alone.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class AutomationStore:
    def __init__(self, path: Path | None = None):
        in_memory = str(path) == ':memory:'
        self.path = Path(':memory:') if in_memory else safe_path(path if path is not None else 'data/automation.db')
        if not in_memory:
            for suffix in ('-wal', '-shm', '-journal'):
                safe_path(Path(str(self.path) + suffix))
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(':memory:' if str(path) == ':memory:' else self.path, timeout=30, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA busy_timeout=30000')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS automation_prompts (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
                policy TEXT NOT NULL, next_publish_at TEXT);
            CREATE TABLE IF NOT EXISTS automation_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id TEXT);
            INSERT OR IGNORE INTO automation_state(singleton) VALUES(1);
            CREATE TABLE IF NOT EXISTS automation_jobs (
                id TEXT PRIMARY KEY, prompt_id TEXT NOT NULL, source_url TEXT NOT NULL,
                channel_id TEXT NOT NULL, video_id TEXT, status TEXT NOT NULL,
                publish_at TEXT, created_at TEXT NOT NULL,
                UNIQUE(source_url,channel_id), UNIQUE(video_id,channel_id));
            CREATE TABLE IF NOT EXISTS automation_attempts (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, snapshot TEXT NOT NULL);
        ''')
        prompt_columns = {row[1] for row in self._db.execute('PRAGMA table_info(automation_prompts)')}
        if 'target_channel_id' not in prompt_columns:
            try:
                self._db.execute('ALTER TABLE automation_prompts ADD COLUMN target_channel_id TEXT')
            except sqlite3.OperationalError:
                if 'target_channel_id' not in {row[1] for row in self._db.execute('PRAGMA table_info(automation_prompts)')}:
                    raise
        columns = {row[1] for row in self._db.execute('PRAGMA table_info(automation_jobs)')}
        if 'owner_pid' not in columns:
            try:
                self._db.execute('ALTER TABLE automation_jobs ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0')
            except sqlite3.OperationalError:
                if 'owner_pid' not in {row[1] for row in self._db.execute('PRAGMA table_info(automation_jobs)')}:
                    raise
        self._registry_key = str(self.path.resolve()) if str(path) != ':memory:' else str(uuid4())
        with _LIVE_LOCK:
            if not _LIVE_STORES.get(self._registry_key):
                with self._transaction():
                    inflight = self._db.execute("SELECT id,owner_pid,status FROM automation_jobs WHERE status IN ('downloading','generating','uploading')").fetchall()
                    for row in inflight:
                        if row['owner_pid'] == os.getpid() or not _process_alive(row['owner_pid']):
                            self._db.execute("UPDATE automation_jobs SET status=? WHERE id=?",
                                             ('uncertain' if row['status'] == 'uploading' else 'failed', row['id']))
            _LIVE_STORES[self._registry_key] = _LIVE_STORES.get(self._registry_key, 0) + 1
        self._closed = False

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def _prompt(self, row):
        if row is None:
            raise ValueError('Không tìm thấy lời nhắc tự động hóa.')
        result = dict(row)
        result['policy'] = AutomationPolicy(**json.loads(result['policy']))
        active = self._db.execute('SELECT active_id FROM automation_state WHERE singleton=1').fetchone()[0]
        result['active'] = result['id'] == active
        return result

    def list_prompts(self) -> list[dict]:
        with self._lock:
            return [self._prompt(row) for row in self._db.execute('SELECT * FROM automation_prompts ORDER BY rowid')]

    def get_prompt(self, id: str) -> dict:
        with self._lock:
            return self._prompt(self._db.execute('SELECT * FROM automation_prompts WHERE id=?', (id,)).fetchone())

    def add_prompt(self, name: str, prompt: str, policy: AutomationPolicy, *, target_channel_id: str | None = None) -> str:
        if type(name) is not str or not name.strip() or len(name) > 200:
            raise ValueError('Tên lời nhắc phải có từ 1 đến 200 ký tự.')
        if type(prompt) is not str or not prompt.strip() or len(prompt) > 20000:
            raise ValueError('Lời nhắc phải có từ 1 đến 20000 ký tự.')
        if not isinstance(policy, AutomationPolicy):
            raise ValueError('Chính sách tự động hóa không hợp lệ.')
        self._validate_target_channel(target_channel_id)
        nonsecret_value([name, prompt, asdict(policy)], reject_text=True)
        id = str(uuid4())
        with self._transaction():
            self._db.execute('INSERT INTO automation_prompts(id,name,prompt,policy,target_channel_id) VALUES(?,?,?,?,?)',
                             (id, name.strip(), prompt.strip(), json.dumps(asdict(policy), ensure_ascii=False), target_channel_id))
        return id

    @staticmethod
    def _validate_target_channel(channel_id):
        if channel_id is not None:
            if type(channel_id) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', channel_id):
                raise ValueError('Mã kênh đích không hợp lệ.')
            nonsecret_value(channel_id, reject_text=True)

    def set_prompt_channel(self, prompt_id, channel_id):
        self._validate_target_channel(channel_id)
        with self._transaction():
            if not self._db.execute('UPDATE automation_prompts SET target_channel_id=? WHERE id=?',
                                    (channel_id, prompt_id)).rowcount:
                raise ValueError('Không tìm thấy prompt.')

    def delete_prompt(self, id: str):
        with self._transaction():
            self._db.execute('UPDATE automation_state SET active_id=NULL WHERE active_id=?', (id,))
            self._db.execute('DELETE FROM automation_prompts WHERE id=?', (id,))

    def set_active(self, id: str | None):
        with self._transaction():
            if id is not None:
                self.get_prompt(id)
            self._db.execute('UPDATE automation_state SET active_id=? WHERE singleton=1', (id,))

    def active_prompt(self) -> dict | None:
        with self._lock:
            id = self._db.execute('SELECT active_id FROM automation_state WHERE singleton=1').fetchone()[0]
            return self.get_prompt(id) if id else None

    def _available_slot(self, record, now, channel_id, exclude_job_id=None):
        policy = record['policy']
        if policy.interval_minutes is None:
            return None
        step = timedelta(minutes=policy.interval_minutes)
        slot = now.replace(hour=policy.start_hour, minute=policy.start_minute, second=0, microsecond=0)
        earliest = now + timedelta(minutes=15)
        # Align in either direction: an afternoon origin still continues hourly
        # through midnight rather than restarting at16:00 the next day.
        slot += ((earliest - slot) // step) * step
        if slot < earliest:
            slot += step
        key, value = ('channel_id', channel_id) if channel_id else ('prompt_id', record['id'])
        rows = self._db.execute(
            f"SELECT id,publish_at FROM automation_jobs WHERE {key}=? AND publish_at IS NOT NULL "
            "AND status NOT IN ('failed','cancelled')", (value,)).fetchall()
        occupied = [datetime.fromisoformat(row['publish_at']).astimezone(LOCAL_TZ)
                    for row in rows if row['id'] != exclude_job_id]
        while any(abs(slot - used) < step for used in occupied):
            slot += step
        return slot

    def next_slot(self, prompt_id, channel_id=None, now=None):
        now = now or datetime.now(LOCAL_TZ)
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Thời gian phải có múi giờ.')
        with self._lock:
            return self._available_slot(self.get_prompt(prompt_id), now.astimezone(LOCAL_TZ), channel_id)

    def claim(self, prompt_id: str, source_url: str, channel_id: str, now: datetime | None = None, *, retry_job_id: str | None = None) -> dict:
        source_url = _canonical_url(source_url)
        if type(channel_id) is not str or not channel_id.strip():
            raise ValueError('Chưa chọn kênh YouTube.')
        nonsecret_value(channel_id, reject_text=True)
        now = now or datetime.now(LOCAL_TZ)
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Thời gian phải có múi giờ.')
        now = now.astimezone(LOCAL_TZ)
        try:
            with self._transaction():
                record = self.get_prompt(prompt_id)
                existing = self._db.execute('SELECT * FROM automation_jobs WHERE source_url=? AND channel_id=?',
                                            (source_url, channel_id.strip())).fetchone()
                if existing is not None:
                    if existing['status'] == 'uncertain':
                        if retry_job_id != existing['id']:
                            raise RetryConfirmationRequired(existing['id'])
                    elif existing['status'] not in {'failed', 'cancelled'}:
                        message = ('Video này đã hoàn tất trên kênh đã chọn.' if existing['status'] == 'done'
                                   else 'Video này đang được xử lý trên kênh đã chọn; chờ tác vụ kết thúc.')
                        raise ValueError(message)
                    # Preserve the previous attempt before resetting a retry reservation.
                    self._db.execute('INSERT INTO automation_attempts(id,job_id,snapshot) VALUES(?,?,?)',
                                     (str(uuid4()), existing['id'], json.dumps(dict(existing))))
                publish_at = self._available_slot(record, now, channel_id.strip(), existing['id'] if existing else None)
                id = existing['id'] if existing is not None else str(uuid4())
                values = (prompt_id, source_url, channel_id.strip(), None, 'downloading',
                          publish_at.isoformat() if publish_at else None, now.isoformat(), os.getpid())
                if existing is None:
                    self._db.execute('INSERT INTO automation_jobs(id,prompt_id,source_url,channel_id,video_id,status,publish_at,created_at,owner_pid) VALUES(?,?,?,?,?,?,?,?,?)',
                                     (id, *values))
                else:
                    self._db.execute('UPDATE automation_jobs SET prompt_id=?,source_url=?,channel_id=?,video_id=?,status=?,publish_at=?,created_at=?,owner_pid=? WHERE id=?',
                                     (*values, id))
                next_slot = self._available_slot(record, now, channel_id.strip())
                self._db.execute('UPDATE automation_prompts SET next_publish_at=? WHERE id=?',
                                 (next_slot.isoformat() if next_slot else None, prompt_id))
                return {'id': id, 'publish_at': publish_at}
        except sqlite3.IntegrityError:
            raise ValueError('Video này đã được nhận xử lý trên kênh đã chọn; không tự động thử lại.') from None

    def bind_video(self, job_id: str, video_id: str):
        if type(video_id) is not str or not video_id.strip():
            raise ValueError('Mã video nguồn không hợp lệ.')
        nonsecret_value(video_id, reject_text=True)
        try:
            with self._transaction():
                changed = self._db.execute('UPDATE automation_jobs SET video_id=? WHERE id=?', (video_id.strip(), job_id)).rowcount
                if not changed:
                    raise ValueError('Không tìm thấy tác vụ.')
        except sqlite3.IntegrityError:
            raise ValueError('Video nguồn đã được nhận xử lý trên kênh này.') from None

    def mark_job(self, job_id: str, status: str):
        if status not in _STATUSES:
            raise ValueError('Trạng thái tác vụ không hợp lệ.')
        with self._transaction():
            if not self._db.execute('UPDATE automation_jobs SET status=? WHERE id=?', (status, job_id)).rowcount:
                raise ValueError('Không tìm thấy tác vụ.')

    def finish(self, job_id: str, video_id: str | None = None):
        if video_id is not None:
            self.bind_video(job_id, video_id)
        self.mark_job(job_id, 'done')

    def list_jobs(self, limit: int = 30) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Giới hạn tác vụ phải từ 1 đến 1000.')
        with self._lock:
            return [dict(row) for row in self._db.execute('SELECT * FROM automation_jobs ORDER BY created_at DESC,rowid DESC LIMIT ?', (limit,))]

    def close(self):
        with self._lock, _LIVE_LOCK:
            if not self._closed:
                self._db.close()
                self._closed = True
                _LIVE_STORES[self._registry_key] -= 1


