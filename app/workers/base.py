"""Base worker abstractions for asynchronous background jobs in Qt.

All long-running tasks run in a QThreadPool using QRunnable or in a QThread.
Background tasks communicate strictly with UI through Qt signals.
"""

from __future__ import annotations

import logging
import traceback
import weakref
from functools import wraps
from threading import RLock, Thread
from typing import Any, Callable, Generic, TypeVar

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.core.cancel import CancelToken

logger = logging.getLogger(__name__)

T = TypeVar('T')

_ACTIVE_WORKERS: dict[int, weakref.ReferenceType] = {}
_WORKERS_LOCK = RLock()
_BACKGROUND_REQUESTS: set[Thread] = set()


def _track_worker_locked(worker: Any) -> None:
    identity = id(worker)
    def expired(reference):
        with _WORKERS_LOCK:
            if _ACTIVE_WORKERS.get(identity) is reference:
                del _ACTIVE_WORKERS[identity]
    _ACTIVE_WORKERS[identity] = weakref.ref(worker, expired)


def register_worker(worker: Any) -> None:
    """Register a newly queued worker without extending its lifetime."""
    with _WORKERS_LOCK:
        worker.lifecycle_state = 'queued'
        _track_worker_locked(worker)


def active_workers() -> tuple[Any, ...]:
    """Snapshot queued/running wrappers; retained completed wrappers are absent."""
    with _WORKERS_LOCK:
        return tuple(worker for reference in tuple(_ACTIVE_WORKERS.values())
                     if (worker := reference()) is not None)


def tracked_run(run):
    """Finish registry bookkeeping even for direct run(), errors or cancellation.

    Apply inside @Slot() so Qt metadata describes the actual wrapped method.
    The wrapper captures the function only, never an individual worker.
    """
    @wraps(run)
    def tracked(self, *args, **kwargs):
        with _WORKERS_LOCK:
            self.lifecycle_state = 'running'
            _track_worker_locked(self)
        try:
            return run(self, *args, **kwargs)
        finally:
            with _WORKERS_LOCK:
                self.lifecycle_state = 'finished'
                _ACTIVE_WORKERS.pop(id(self), None)
    return tracked


def cancel_all_workers() -> None:
    """Request cooperative cancellation; this does not interrupt blocking SDKs."""
    for worker in active_workers():
        cancel = getattr(worker, 'cancel', None)
        if callable(cancel):
            cancel()


def background_requests() -> tuple[Thread, ...]:
    """Requests still executing after Qt wrappers may have timed out/cancelled."""
    with _WORKERS_LOCK:
        _BACKGROUND_REQUESTS.intersection_update(
            request for request in tuple(_BACKGROUND_REQUESTS) if request.is_alive())
        return tuple(_BACKGROUND_REQUESTS)


def start_background_request(target: Callable[[], None], *, name: str) -> Thread:
    """Start an observable daemon request; callers cannot force-stop its SDK."""
    with _WORKERS_LOCK:
        background_requests()
        request = Thread(target=target, name=name, daemon=True)
        _BACKGROUND_REQUESTS.add(request)
        try:
            request.start()
        except BaseException:
            _BACKGROUND_REQUESTS.discard(request)
            raise
        return request


class WorkerSignals(QObject):
    """Signals emitted by background workers.

    progress: float between 0.0 and 1.0
    finished: result payload of successful execution
    error: error message string
    cancelled: emitted when the worker was cancelled before or during execution
    """

    progress = Signal(float)
    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    model_selected = Signal(str, str)
    accounts_loaded = Signal(object)
    channel_result = Signal(str, object)


class TaskWorker(QRunnable, Generic[T]):
    """Generic QRunnable worker wrapping a synchronous task.

    Features:
    - Integrates with CancelToken for cooperative cancellation
    - Bridges synchronous progress callbacks to Qt signals safely
    - Emits signals only on main thread via Qt signal-slot mechanism
    """

    def __init__(
        self,
        task: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self.cancel_token.cancel()

    def _on_progress(self, progress: float) -> None:
        """Callback passed to task to report progress safely via signal."""
        # Note: Qt signals are thread-safe when emitted across threads
        self.signals.progress.emit(max(0.0, min(1.0, float(progress))))

    @Slot()
    @tracked_run
    def run(self) -> None:
        """Worker main execution loop in background thread."""
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return

        try:
            # We inject on_progress and cancel_token if the task accepts them,
            # or pass through arguments.
            result = self.task(
                *self.args,
                on_progress=self._on_progress,
                cancel_token=self.cancel_token,
                **self.kwargs,
            )
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(result)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                error_msg = str(exc) or exc.__class__.__name__
                logger.error("Worker task failed: %s\n%s", error_msg, traceback.format_exc())
                self.signals.error.emit(error_msg)
