"""Worker teardown must distinguish retained wrappers from active work."""
import threading
from types import SimpleNamespace

import pytest

from app.contracts import GeneratedContent
from app.workers import base
from app.workers.base import TaskWorker
from app.workers.service_workers import GenerateContentWorker, YouTubeRestoreWorker
from app.ui.model_loading import _ModelWorker


def test_retained_direct_worker_unregisters_and_stays_uncancelled(qapp):
    worker = TaskWorker(lambda **kwargs: 'done')
    assert worker in base.active_workers()
    assert worker.lifecycle_state == 'queued'
    worker.run()
    assert worker.lifecycle_state == 'finished'
    assert worker not in base.active_workers()
    base.cancel_all_workers()
    assert not worker.cancel_token.is_cancelled


def test_worker_unregistered_when_task_raises(qapp):
    worker = TaskWorker(lambda **kwargs: (_ for _ in ()).throw(ValueError('expected')))
    worker.run()
    assert worker not in base.active_workers()
    assert worker.lifecycle_state == 'finished'


def test_model_worker_cancellation_discards_catalog_and_unregisters(qapp):
    entered, release = threading.Event(), threading.Event()
    def models():
        entered.set()
        assert release.wait(2)
        return ['model']
    worker = _ModelWorker(SimpleNamespace(list_models=models))
    loaded = []
    worker.signals.loaded.connect(loaded.append)
    thread = threading.Thread(target=worker.run)
    try:
        thread.start()
        assert entered.wait(2)
        assert worker.lifecycle_state == 'running'
        worker.cancel()
    finally:
        release.set()
        thread.join(2)
    qapp.processEvents()
    assert not loaded
    assert worker not in base.active_workers()


def test_restore_cancelled_inside_restore_does_not_publish(qapp):
    results, cancelled = [], []
    def restore():
        worker.cancel()
        return None
    class Service:
        def list_accounts(self): return []
        def restore_session(self): return restore()
    worker = YouTubeRestoreWorker(Service())
    worker.signals.finished.connect(results.append)
    worker.signals.cancelled.connect(lambda: cancelled.append(True))
    worker.run()
    assert results == []
    assert cancelled == [True]
    assert worker not in base.active_workers()


def test_cancelled_ai_wrapper_keeps_detached_request_observable(qapp):
    entered, release = threading.Event(), threading.Event()
    def generate(*args):
        entered.set()
        assert release.wait(2)
        return GeneratedContent('title', 'description', [], [])
    worker = GenerateContentWorker(SimpleNamespace(generate=generate), None)
    thread = threading.Thread(target=worker.run)
    try:
        thread.start()
        assert entered.wait(2)
        worker.cancel()
        thread.join(2)
        assert not thread.is_alive()
        assert worker not in base.active_workers()
        requests = base.background_requests()
        assert any(request.name == 'studio-ai-request' for request in requests)
    finally:
        release.set()
        thread.join(2)
        for request in base.background_requests():
            request.join(2)
    assert not base.background_requests()


def test_registry_does_not_keep_unstarted_worker_alive(qapp):
    import gc
    import weakref
    worker = TaskWorker(lambda **kwargs: None)
    reference = weakref.ref(worker)
    del worker
    gc.collect()
    assert reference() is None


def test_precancelled_model_catalog_is_never_called(qapp):
    from unittest.mock import Mock
    generator = SimpleNamespace(list_models=Mock())
    worker = _ModelWorker(generator)
    worker.cancel()
    worker.run()
    generator.list_models.assert_not_called()
    assert worker.lifecycle_state == 'finished'
    assert worker not in base.active_workers()


def test_coordinator_cancellation_does_not_poison_shared_snapshot(qapp):
    from app.core.cancel import CancelToken
    from app.errors import Cancelled
    from app.workers.youtube_restore import fetch_accounts
    token = CancelToken()
    class Service:
        def list_accounts(self):
            token.cancel()
            return []
    service = Service()
    with pytest.raises(Cancelled):
        fetch_accounts(service, token=token)
    # Another consumer can still use the valid completed snapshot.
    assert fetch_accounts(service, consumer='restore') == []
