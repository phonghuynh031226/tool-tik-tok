"""Keep the Clivo avatar's independent Qt TLS path offline during mock tests."""
from unittest.mock import Mock
import pytest


@pytest.fixture(scope='session', autouse=True)
def no_real_qt_avatar_downloads():
    # Session scope also covers queued signals delivered during Qt teardown or
    # between service/UI test fixtures. Dedicated image tests inject replies.
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(QNetworkAccessManager, 'get', lambda self, request: Mock(
            error=Mock(return_value=QNetworkReply.NetworkError.HostNotFoundError)))
        yield


def pytest_configure(config):
    config.addinivalue_line('markers', 'background_tasks: explicitly exercise automatically started fake background work')


@pytest.fixture(autouse=True)
def fake_background_defaults(monkeypatch, request):
    from app.ui.services import ServiceContainer
    monkeypatch.setattr(ServiceContainer, 'automatic_background_tasks',
                        request.node.get_closest_marker('background_tasks') is not None)


def _cleanup_qt_resources():
    """Reach quiescence within the pre-existing 1000 ms budget, not a fixed wait.

    Never clear queued work before it can emit cancellation. Stop producers,
    process terminal signals, then deliver deferred QObject deletion explicitly.
    """
    from PySide6.QtCore import QCoreApplication, QThreadPool, QEvent
    from PySide6.QtWidgets import QApplication, QMainWindow
    from shiboken6 import isValid
    from app.workers.base import cancel_all_workers, background_requests
    app = QCoreApplication.instance()
    windows = list(app.topLevelWidgets()) if isinstance(app, QApplication) else []
    for window in windows:
        if isinstance(window, QMainWindow) and isValid(window):
            controller = getattr(window, 'automation', None)
            if controller is not None and not getattr(window, '_resources_closed', False):
                controller.deactivate()
            window.close()
    pool = QThreadPool.globalInstance()
    deadline = time.monotonic() + 1.0
    done = False
    while time.monotonic() < deadline:
        cancel_all_workers()
        if app is not None:
            app.processEvents()
        done = pool.waitForDone(1)
        requests = background_requests()
        for thread in requests:
            thread.join(timeout=.001)
        if done and not background_requests():
            if app is not None:
                app.processEvents()
            if pool.activeThreadCount() == 0:
                break
    assert done and pool.activeThreadCount() == 0 and not background_requests(), (
        'Qt/background work did not stop within the existing 1000 ms cleanup budget')
    for window in windows:
        if isinstance(window, QMainWindow) and isValid(window):
            window.close()
            window.deleteLater()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert pool.activeThreadCount() == 0, 'Deferred events started work after teardown'


@pytest.fixture(autouse=True)
def cleanup_resources_between_tests(request):
    _cleanup_qt_resources()
    yield
    _record_qt_resources(request.node.nodeid, 'before_cleanup')
    try:
        _cleanup_qt_resources()
    finally:
        _record_qt_resources(request.node.nodeid, 'after_cleanup')


# Diagnostic snapshots intentionally contain type names/states only, never UI
# text, settings, credentials or worker arguments. Keep them in this worktree.
import gc
import json
import os
import sys
import threading
import time
from pathlib import Path

_TRACE_PATH = Path(__file__).resolve().parents[1] / '.cache' / 'qt-lifecycle' / (os.environ.get('STUDIO_QT_TRACE', 'baseline') + '.jsonl')


def _record_qt_resources(nodeid, phase):
    from PySide6.QtCore import QCoreApplication, QThreadPool, QThread, QTimer, QRunnable
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid
    from app.workers.base import active_workers
    pool = QThreadPool.globalInstance()
    registered = {id(worker) for worker in active_workers()}
    timers, threads, workers, windows = [], [], [], []
    for obj in gc.get_objects():
        try:
            if isinstance(obj, QTimer) and isValid(obj) and obj.isActive():
                parent = obj.parent()
                timers.append({'type': type(obj).__name__, 'parent': type(parent).__name__,
                               'interval': obj.interval(), 'single_shot': obj.isSingleShot()})
            elif isinstance(obj, QThread) and isValid(obj) and obj.isRunning():
                threads.append(type(obj).__name__ + ':' + obj.objectName())
            elif isinstance(obj, QRunnable) and isValid(obj):
                token = getattr(obj, 'cancel_token', None)
                workers.append({'type': type(obj).__name__,
                                'cancelled': bool(token and token.is_cancelled),
                                'registered': id(obj) in registered,
                                'state': getattr(obj, 'lifecycle_state', 'unknown')})
        except (RuntimeError, ReferenceError):
            continue
    app = QApplication.instance()
    if isinstance(app, QApplication):
        for widget in app.topLevelWidgets():
            if type(widget).__name__ == 'MainWindow' and isValid(widget):
                controller = getattr(widget, 'automation', None)
                windows.append({'type': 'MainWindow', 'visible': widget.isVisible(),
                                'automation_busy': bool(controller and controller.busy),
                                'automation_stage': getattr(controller, 'stage', '')})
    frames = []
    for thread_id, frame in sys._current_frames().items():
        if thread_id == threading.get_ident():
            continue
        frames.append({'thread_id': thread_id, 'function': frame.f_code.co_name,
                       'file': Path(frame.f_code.co_filename).name, 'line': frame.f_lineno})
    row = {'test': nodeid, 'phase': phase, 'time': time.monotonic(),
           'pool_active': pool.activeThreadCount(), 'pool_max': pool.maxThreadCount(),
           'workers': workers, 'timers': timers, 'qthreads': threads,
           'windows': windows, 'python_threads': frames}
    _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _TRACE_PATH.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
