from unittest.mock import Mock
from PySide6.QtCore import QThreadPool
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def test_fake_window_can_disable_automatic_background_tasks(qtbot, monkeypatch):
    services = ServiceContainer.create_fake()
    services.automatic_background_tasks = False
    start = Mock()
    monkeypatch.setattr(QThreadPool.globalInstance(), 'start', start)
    window = MainWindow(services)
    qtbot.addWidget(window)
    assert not window.page_history._countdown_timer.isActive()
    start.assert_not_called()


def test_closing_window_cancels_retained_account_restore(qtbot):
    services = ServiceContainer.create_fake()
    window = MainWindow(services)
    qtbot.addWidget(window)
    restore_worker = Mock()
    services.connection._worker = restore_worker
    window.close()
    restore_worker.cancel.assert_called_once()
