from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pytest

from app.core.automation import AutomationPolicy, AutomationStore, LOCAL_TZ


@pytest.mark.parametrize('kwargs', [
    {'made_for_kids': 0}, {'privacy': 'PUBLIC'}, {'interval_minutes': True},
    {'interval_minutes': 0}, {'interval_minutes': 1441}, {'start_hour': True},
    {'start_hour': 24}, {'start_minute': -1}, {'content_instructions': None},
])
def test_policy_strict(kwargs):
    with pytest.raises(ValueError):
        AutomationPolicy(**kwargs)


def test_scheduled_policy_is_private():
    policy = AutomationPolicy(privacy='public', interval_minutes=60)
    assert policy.privacy == 'private'
    assert 'UTC+7' in policy.summary()


def add(store, **kwargs):
    return store.add_prompt('Mỗi giờ', 'Tải TikTok, AI, đăng YouTube không dành cho trẻ em', AutomationPolicy(**kwargs))


def test_persistence_single_active_and_recovery(tmp_path):
    path = tmp_path / 'automation.db'
    store = AutomationStore(path)
    first, second = add(store), add(store)
    store.set_active(first)
    store.set_active(second)
    assert [p['id'] for p in store.list_prompts() if p['active']] == [second]
    job = store.claim(second, 'https://www.tiktok.com/@a/video/12', 'channel')
    store.mark_job(job['id'], 'uploading')
    store.close()
    store = AutomationStore(path)
    assert store.active_prompt()['id'] == second
    assert store.list_jobs()[0]['status'] == 'uncertain'
    with pytest.raises(ValueError):
        store.claim(second, 'https://www.tiktok.com/@b/video/12?x=1', 'channel')
    store.delete_prompt(second)
    assert store.active_prompt() is None
    assert store.list_jobs()[0]['status'] == 'uncertain'
    store.close()


def test_schedule_rollover_and_fifteen_minute_margin():
    store = AutomationStore(':memory:')
    prompt = add(store, interval_minutes=60)
    now = datetime(2026, 11, 16, 22, 56, tzinfo=LOCAL_TZ)
    job = store.claim(prompt, 'https://vm.tiktok.com/a', 'c', now)
    assert job['publish_at'] == datetime(2026, 11, 17, 0, 0, tzinfo=LOCAL_TZ)
    next_job = store.claim(prompt, 'https://vm.tiktok.com/b', 'c', now)
    assert next_job['publish_at'].hour == 1
    store.close()


def test_duplicate_claim_rolls_back_schedule_and_bind_protects_channel():
    store = AutomationStore(':memory:')
    prompt = add(store, interval_minutes=60)
    job = store.claim(prompt, 'https://vm.tiktok.com/a', 'one')
    slot = store.get_prompt(prompt)['next_publish_at']
    with pytest.raises(ValueError):
        store.claim(prompt, 'https://vm.tiktok.com/a?share=2', 'one')
    assert store.get_prompt(prompt)['next_publish_at'] == slot
    store.bind_video(job['id'], '123')
    alias = store.claim(prompt, 'https://vm.tiktok.com/b', 'one')
    with pytest.raises(ValueError):
        store.bind_video(alias['id'], '123')
    other = store.claim(prompt, 'https://vm.tiktok.com/a', 'two')
    store.bind_video(other['id'], '123')
    store.finish(job['id'])
    assert next(j for j in store.list_jobs() if j['id'] == job['id'])['status'] == 'done'
    store.close()


def test_concurrent_instances_atomic_and_live_claim_unchanged(tmp_path):
    path = tmp_path / 'db.sqlite'
    first = AutomationStore(path)
    prompt = add(first, interval_minutes=60)
    job = first.claim(prompt, 'https://vm.tiktok.com/start', 'c')
    second = AutomationStore(path)
    assert second.list_jobs()[0]['status'] == 'downloading'
    def claim(store):
        try:
            return store.claim(prompt, 'https://vm.tiktok.com/same', 'c')['id']
        except ValueError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, [first, second]))
    assert sum(value is not None for value in results) == 1
    assert len(first.list_jobs()) == 2
    first.close()
    second.close()


def test_no_secret_persistence_or_naive_time():
    store = AutomationStore(':memory:')
    with pytest.raises(ValueError):
        store.add_prompt('bad', 'api_key=unsafe', AutomationPolicy())
    prompt = add(store)
    with pytest.raises(ValueError):
        store.claim(prompt, 'https://vm.tiktok.com/a', 'c', datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        store.claim(prompt, 'https://example.com/video/1', 'c')
    store.close()


def test_other_live_process_claim_is_not_recovered(tmp_path, monkeypatch):
    import app.core.automation as automation
    path = tmp_path / 'db.sqlite'
    store = AutomationStore(path)
    prompt = add(store)
    job = store.claim(prompt, 'https://vm.tiktok.com/a', 'c')
    store._db.execute('UPDATE automation_jobs SET owner_pid=999999 WHERE id=?', (job['id'],))
    store.close()
    monkeypatch.setattr(automation, '_process_alive', lambda pid: True)
    store = AutomationStore(path)
    assert store.list_jobs()[0]['status'] == 'downloading'
    store.close()
    monkeypatch.setattr(automation, '_process_alive', lambda pid: False)
    store = AutomationStore(path)
    assert store.list_jobs()[0]['status'] == 'failed'
    store.close()


def test_store_rejects_escape_before_creating_directory_or_connecting(tmp_path, monkeypatch):
    import app.core.paths as paths
    import app.core.automation as automation
    root = tmp_path / 'app'
    root.mkdir()
    monkeypatch.setattr(paths, 'project_root', lambda: root)
    def forbidden_connect(*args, **kwargs):
        pytest.fail('Rejected paths must not reach SQLite')
    monkeypatch.setattr(automation.sqlite3, 'connect', forbidden_connect)
    escaped = tmp_path / 'outside' / 'automation.db'
    with pytest.raises(ValueError):
        AutomationStore(escaped)
    with pytest.raises(ValueError):
        AutomationStore('../outside/automation.db')
    assert not escaped.parent.exists()


def test_store_default_and_relative_paths_use_project_root_not_cwd(tmp_path, monkeypatch):
    import app.core.paths as paths
    root = tmp_path / 'app'
    root.mkdir()
    elsewhere = tmp_path / 'cwd'
    elsewhere.mkdir()
    monkeypatch.setattr(paths, 'project_root', lambda: root)
    monkeypatch.chdir(elsewhere)
    store = AutomationStore()
    assert store.path == root / 'data' / 'automation.db'
    store.close()
    store = AutomationStore('custom/prompts.db')
    assert store.path == root / 'custom' / 'prompts.db'
    store.close()
    assert not (elsewhere / 'data').exists()


def test_store_default_path_follows_frozen_executable(tmp_path, monkeypatch):
    import sys
    frozen_root = tmp_path / 'frozen'
    frozen_root.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(frozen_root / 'studio.exe'))
    store = AutomationStore()
    assert store.path == frozen_root / 'data' / 'automation.db'
    store.close()


def _local_symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'Cannot create symlink with current Windows permissions: {type(error).__name__}')


@pytest.mark.parametrize('kind', ['database', 'directory', '-wal', '-shm', '-journal'])
def test_store_rejects_existing_symlinks_and_sqlite_sidecars(tmp_path, monkeypatch, kind):
    import app.core.paths as paths
    root = tmp_path / 'app'
    root.mkdir()
    monkeypatch.setattr(paths, 'project_root', lambda: root)
    database = root / 'automation.db'
    if kind == 'directory':
        target = root / 'real'
        target.mkdir()
        linked_directory = root / 'linked'
        _local_symlink(linked_directory, target, directory=True)
        database = linked_directory / 'automation.db'
    else:
        target = root / 'target-file'
        target.write_bytes(b'unchanged')
        link = database if kind == 'database' else root / ('automation.db' + kind)
        _local_symlink(link, target)
    with pytest.raises(ValueError):
        AutomationStore(database)
    if kind != 'directory':
        assert target.read_bytes() == b'unchanged'
    if kind != 'database':
        assert not database.exists()


def test_in_memory_store_does_not_consult_or_create_disk_paths(monkeypatch):
    import app.core.automation as automation
    def forbidden_safe_path(*args, **kwargs):
        pytest.fail('In-memory stores must not use disk paths')
    monkeypatch.setattr(automation, 'safe_path', forbidden_safe_path)
    store = AutomationStore(':memory:')
    assert store.list_prompts() == []
    store.close()


def test_one_minute_interval_reserves_fifteen_minutes_for_validation_and_processing():
    from datetime import timedelta
    store = AutomationStore(':memory:')
    prompt = add(store, interval_minutes=1)
    now = datetime(2026, 11, 16, 10, 0, 30, tzinfo=LOCAL_TZ)
    job = store.claim(prompt, 'https://vm.tiktok.com/short-interval', 'c', now)
    assert job['publish_at'] == datetime(2026, 11, 16, 10, 16, tzinfo=LOCAL_TZ)
    assert job['publish_at'] - now >= timedelta(minutes=15)
    assert '15 phút' in store.get_prompt(prompt)['policy'].summary()
    store.close()


@pytest.mark.parametrize('status',['failed','cancelled'])
def test_preupload_terminal_job_can_retry_and_keeps_attempt_snapshot(status):
    store=AutomationStore(':memory:')
    prompt=add(store)
    old=store.claim(prompt,'https://vm.tiktok.com/retry','c')
    store.mark_job(old['id'],'generating')
    store.mark_job(old['id'],status)
    new=store.claim(prompt,'https://vm.tiktok.com/retry','c')
    assert new['id']==old['id']
    assert store.list_jobs()[0]['status']=='downloading'
    assert store._db.execute('SELECT count(*) FROM automation_attempts').fetchone()[0]==1
    store.close()


def test_uncertain_retry_requires_explicit_confirmation_for_exact_job():
    from app.core.automation import RetryConfirmationRequired
    store=AutomationStore(':memory:')
    prompt=add(store)
    old=store.claim(prompt,'https://vm.tiktok.com/retry','c')
    store.mark_job(old['id'],'uncertain')
    with pytest.raises(RetryConfirmationRequired) as error:
        store.claim(prompt,'https://vm.tiktok.com/retry','c')
    assert error.value.job_id==old['id']
    with pytest.raises(RetryConfirmationRequired):
        store.claim(prompt,'https://vm.tiktok.com/retry','c',retry_job_id='different')
    store.claim(prompt,'https://vm.tiktok.com/retry','c',retry_job_id=old['id'])
    store.close()


@pytest.mark.parametrize('status',['downloading','generating','uploading','done'])
def test_retry_confirmation_cannot_override_active_or_done(status):
    store=AutomationStore(':memory:')
    prompt=add(store)
    old=store.claim(prompt,'https://vm.tiktok.com/retry','c')
    store.mark_job(old['id'],status)
    with pytest.raises(ValueError):
        store.claim(prompt,'https://vm.tiktok.com/retry','c',retry_job_id=old['id'])
    store.close()


def test_crash_before_upload_is_failed_and_retryable(tmp_path):
    store=AutomationStore(tmp_path/'recovery.db')
    prompt=add(store)
    old=store.claim(prompt,'https://vm.tiktok.com/retry','c')
    store.mark_job(old['id'],'generating')
    store.close()
    store=AutomationStore(tmp_path/'recovery.db')
    assert store.list_jobs()[0]['status']=='failed'
    store.claim(prompt,'https://vm.tiktok.com/retry','c')
    store.close()


def test_stale_cursor_from_failed_attempt_does_not_skip_next_hour():
    store=AutomationStore(':memory:')
    prompt=add(store,interval_minutes=60,start_hour=16)
    now=datetime(2026,11,17,18,4,tzinfo=LOCAL_TZ)
    store._db.execute('UPDATE automation_prompts SET next_publish_at=? WHERE id=?',
                      (datetime(2026,11,17,20,0,tzinfo=LOCAL_TZ).isoformat(),prompt))
    first=store.claim(prompt,'https://vm.tiktok.com/first','c',now)
    assert first['publish_at']==datetime(2026,11,17,19,0,tzinfo=LOCAL_TZ)
    store.finish(first['id'])
    second=store.claim(prompt,'https://vm.tiktok.com/second','c',now)
    assert second['publish_at']==datetime(2026,11,17,20,0,tzinfo=LOCAL_TZ)
    store.close()


def test_failed_retry_reuses_unconsumed_hour():
    store=AutomationStore(':memory:')
    prompt=add(store,interval_minutes=60)
    now=datetime(2026,11,17,18,4,tzinfo=LOCAL_TZ)
    first=store.claim(prompt,'https://vm.tiktok.com/retry-slot','c',now)
    store.mark_job(first['id'],'failed')
    retry=store.claim(prompt,'https://vm.tiktok.com/retry-slot','c',now)
    assert retry['publish_at']==first['publish_at']
    store.finish(retry['id'])
    next_job=store.claim(prompt,'https://vm.tiktok.com/next-slot','c',now)
    assert next_job['publish_at'].hour==20
    store.close()


def test_next_slot_preview_ignores_abandoned_cursor_but_preserves_uploaded_slots():
    store=AutomationStore(':memory:')
    prompt=add(store,interval_minutes=60)
    now=datetime(2026,11,17,18,4,tzinfo=LOCAL_TZ)
    first=store.claim(prompt,'https://vm.tiktok.com/occupied','c',now)
    store.finish(first['id'])
    store._db.execute('UPDATE automation_prompts SET next_publish_at=? WHERE id=?',
                     ('2026-11-18T03:00:00+07:00',prompt))
    assert store.next_slot(prompt,'c',now).hour==20
    assert store.next_slot(prompt,'another',now).hour==19
    store.close()



def test_hourly_sequence_continues_after_midnight_with_afternoon_origin():
    store=AutomationStore(':memory:')
    prompt=add(store,interval_minutes=60,start_hour=16)
    first=store.claim(prompt,'https://vm.tiktok.com/midnight','c',datetime(2026,11,17,23,40,tzinfo=LOCAL_TZ))
    assert first['publish_at']==datetime(2026,11,18,0,0,tzinfo=LOCAL_TZ)
    store.finish(first['id'])
    second=store.claim(prompt,'https://vm.tiktok.com/after-midnight','c',datetime(2026,11,18,0,4,tzinfo=LOCAL_TZ))
    assert second['publish_at']==datetime(2026,11,18,1,0,tzinfo=LOCAL_TZ)
    store.close()



def test_prompt_channel_target_persists_and_old_prompts_default_auto(tmp_path):
    path=tmp_path/'prompt-target.db'
    store=AutomationStore(path)
    automatic=add(store)
    chosen=store.add_prompt('Chosen','User prompt',AutomationPolicy(),target_channel_id='UC'+'b'*22)
    assert store.get_prompt(automatic)['target_channel_id'] is None
    store.close()
    store=AutomationStore(path)
    assert store.get_prompt(chosen)['target_channel_id']=='UC'+'b'*22
    store.set_prompt_channel(chosen,None)
    assert store.get_prompt(chosen)['target_channel_id'] is None
    store.close()



def test_old_prompt_database_migrates_target_without_changing_content(tmp_path):
    import sqlite3,json
    from dataclasses import asdict
    path=tmp_path/'legacy.db'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE automation_prompts (id TEXT PRIMARY KEY,name TEXT NOT NULL,prompt TEXT NOT NULL,policy TEXT NOT NULL,next_publish_at TEXT)')
    db.execute('INSERT INTO automation_prompts VALUES(?,?,?,?,?)',
               ('legacy','Old name','Old prompt',json.dumps(asdict(AutomationPolicy())),'2026-11-17T20:00:00+07:00'))
    db.commit(); db.close()
    store=AutomationStore(path)
    record=store.get_prompt('legacy')
    assert record['target_channel_id'] is None
    assert (record['name'],record['prompt'],record['next_publish_at'])==('Old name','Old prompt','2026-11-17T20:00:00+07:00')
    store.close()
