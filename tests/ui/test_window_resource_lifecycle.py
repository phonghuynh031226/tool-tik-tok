"""A closed window releases resources even while its Python wrapper is retained."""
from unittest.mock import Mock
import sqlite3

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app.core.automation import AutomationPolicy, AutomationStore
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


@pytest.mark.background_tasks
def test_close_stops_timers_appearance_and_owned_workers(qtbot, monkeypatch):
    window = MainWindow(ServiceContainer.create_fake())
    qtbot.addWidget(window)
    preferences = window.ui_preferences
    refresh = Mock(wraps=preferences._apply_widget)
    monkeypatch.setattr(preferences, '_apply_widget', refresh)
    # Queue appearance work immediately before closing, without dispatching it.
    QApplication.sendEvent(window.page_dashboard, QEvent(QEvent.Type.LayoutRequest))
    worker = Mock()
    window.page_dashboard._active_download_worker = worker
    assert window.page_history._countdown_timer.isActive()
    window.close()
    services = window.services
    services.connection.changed.emit()
    window.close()  # teardown may close an already closed window again
    QApplication.sendEvent(window.page_dashboard, QEvent(QEvent.Type.LayoutRequest))
    QApplication.processEvents()
    assert isValid(window)  # close must work without requiring QObject destruction
    assert not any(timer.isActive() for timer in window.findChildren(QTimer))
    refresh.assert_not_called()
    worker.cancel.assert_called_once()


def test_close_closes_only_window_owned_store(qtbot):
    window = MainWindow(ServiceContainer.create_fake())
    qtbot.addWidget(window)
    store = window.automation.store
    window.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.list_jobs()

    services = ServiceContainer.create_fake()
    services.automation_store = AutomationStore(':memory:')
    injected = MainWindow(services)
    qtbot.addWidget(injected)
    injected.close()
    assert services.automation_store.list_jobs() == []
    services.automation_store.close()


def test_close_prevents_queued_startup_restore(qtbot, monkeypatch):
    services = ServiceContainer.create_fake()
    window = MainWindow(services)
    qtbot.addWidget(window)
    monkeypatch.setattr(ServiceContainer, 'is_fake', property(lambda self: False))
    services.connection.restore_service = Mock()
    window.close()
    QApplication.processEvents()
    services.connection.restore_service.assert_not_called()



def test_busy_close_keeps_job_and_store_until_cancellation_finishes(qtbot):
    services = ServiceContainer.create_fake()
    services.automation_store = AutomationStore(':memory:')
    window = MainWindow(services)
    qtbot.addWidget(window)
    store = services.automation_store
    pid = store.add_prompt('Pending', 'Demo', AutomationPolicy())
    job = store.claim(pid, 'https://www.tiktok.com/@demo/video/1234567890', 'channel')
    window.automation.job = job
    window.automation.stage = 'downloading'
    worker = Mock()
    window.page_dashboard._active_download_worker = worker
    assert window.close() is False
    assert window.automation.job is job
    assert store.list_jobs()[0]['status'] != 'cancelled'
    assert not window._resources_closed
    worker.cancel.assert_called_once()
    window.automation._cancelled()
    qtbot.waitUntil(lambda: window._resources_closed)
    assert store.list_jobs()[0]['status'] == 'cancelled'
    store.close()
