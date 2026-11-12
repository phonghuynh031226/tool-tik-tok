"""Base worker abstractions for asynchronous background jobs in Qt.

All long-running tasks run in a QThreadPool using QRunnable or in a QThread.
Background tasks communicate strictly with UI through Qt signals.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Generic, TypeVar

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.core.cancel import CancelToken

logger = logging.getLogger(__name__)

T = TypeVar('T')


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

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self.cancel_token.cancel()

    def _on_progress(self, progress: float) -> None:
        """Callback passed to task to report progress safely via signal."""
        # Note: Qt signals are thread-safe when emitted across threads
        self.signals.progress.emit(max(0.0, min(1.0, float(progress))))

    @Slot()
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
