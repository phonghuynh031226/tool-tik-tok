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
