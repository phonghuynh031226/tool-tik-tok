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


@pytest.fixture(autouse=True)
def cleanup_resources_between_tests():
    """Ensure background threads/workers on QThreadPool finish between tests."""
    from PySide6.QtCore import QCoreApplication, QThreadPool
    from app.workers.base import cancel_all_workers

    def _cleanup():
        cancel_all_workers()
        pool = QThreadPool.globalInstance()
        pool.clear()
        pool.waitForDone(1000)
        app = QCoreApplication.instance()
        if app:
            app.processEvents()

    _cleanup()
    yield
    _cleanup()
