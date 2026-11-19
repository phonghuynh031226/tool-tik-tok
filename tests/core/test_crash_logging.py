"""Startup diagnostics without triggering a native crash or external services."""

import builtins
import platform
import ssl
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.security import logging as studio_logging


@pytest.fixture
def crash_handler(monkeypatch):
    monkeypatch.setattr(studio_logging, '_crash_log_stream', None)
    enable = Mock()
    monkeypatch.setattr(studio_logging.faulthandler, 'enable', enable)
    yield enable
    stream = studio_logging._crash_log_stream
    if stream is not None:
        stream.close()


def test_crash_file_is_retained_and_repeated_enable_reuses_descriptor(tmp_path, crash_handler):
    path = tmp_path / 'logs' / 'crash.log'
    studio_logging.enable_crash_logging(path)
    stream = studio_logging._crash_log_stream
    assert path.is_file()
    assert not stream.closed
    crash_handler.assert_called_once_with(file=stream, all_threads=True)
    studio_logging.enable_crash_logging(path)
    assert studio_logging._crash_log_stream is stream
    assert not stream.closed
    assert crash_handler.call_count == 2


def test_retargeting_crash_file_closes_previous_only_after_enable(tmp_path, crash_handler):
    studio_logging.enable_crash_logging(tmp_path / 'first.log')
    first = studio_logging._crash_log_stream
    def check_previous_open(**kwargs):
        assert not first.closed
    crash_handler.side_effect = check_previous_open
    studio_logging.enable_crash_logging(tmp_path / 'second.log')
    assert first.closed
    assert not studio_logging._crash_log_stream.closed


def test_failed_enable_preserves_previous_descriptor(tmp_path, crash_handler):
    studio_logging.enable_crash_logging(tmp_path / 'first.log')
    first = studio_logging._crash_log_stream
    crash_handler.side_effect = OSError('cannot install handler')
    with pytest.raises(OSError):
        studio_logging.enable_crash_logging(tmp_path / 'second.log')
    assert studio_logging._crash_log_stream is first
    assert not first.closed
    assert crash_handler.call_args.kwargs['file'].closed


def test_startup_enables_crash_log_before_qt_import_and_window(monkeypatch, tmp_path, crash_handler):
    import main

    events = []
    original_import = builtins.__import__

    def record_import(name, *args, **kwargs):
        if name.startswith('PySide6'):
            events.append('qt-import')
        return original_import(name, *args, **kwargs)

    def install_handler():
        studio_logging.enable_crash_logging(tmp_path / 'crash.log')
        events.append('crash-enabled')

    def configure(**kwargs):
        events.append('logging')
        return studio_logging.configure_logging(tmp_path / 'studio.log', **kwargs)

    application = SimpleNamespace(exec=lambda: 23,
        setApplicationName=lambda name: events.append(('name', name)),
        setApplicationDisplayName=lambda name: events.append(('display', name)),
        setWindowIcon=lambda icon: events.append('app-icon'))
    from app.ui import branding
    icon = Mock()
    icon.isNull.return_value = False
    monkeypatch.setattr(branding, 'get_app_icon', lambda: icon)
    from app.core import runtime_env
    monkeypatch.setattr(runtime_env, 'configure_native_environment', lambda: events.append('runtime-env'))
    widgets = SimpleNamespace(QApplication=lambda argv: application)
    window = SimpleNamespace(show=lambda: events.append('show'),
        setWindowIcon=lambda icon: events.append('window-icon'))
    monkeypatch.setitem(sys.modules, 'PySide6.QtWidgets', widgets)
    monkeypatch.setattr(builtins, '__import__', record_import)
    monkeypatch.setattr(main, 'enable_crash_logging', install_handler)
    monkeypatch.setattr(main, 'configure_logging', configure)
    monkeypatch.setattr(main, 'create_window', lambda: (events.append('window'), window)[1])
    try:
        assert main.main() == 23
        assert events[0] == 'crash-enabled'
        assert events.index('crash-enabled') < events.index('runtime-env') < events.index('qt-import')
        assert ('name', 'Clivo') in events and ('display', 'Clivo') in events
        assert 'app-icon' in events and 'window-icon' in events
        assert events.index('crash-enabled') < events.index('qt-import') < events.index('window')
        assert (tmp_path / 'crash.log').is_file()
        text = (tmp_path / 'studio.log').read_text(encoding='utf-8')
        from PySide6.QtCore import qVersion
        assert 'khởi động' in text
        assert f'Python {platform.python_version()}' in text
        assert ssl.OPENSSL_VERSION in text
        assert f'Qt {qVersion()}' in text
    finally:
        logger = studio_logging.logging.getLogger('TikTokYouTubeStudio')
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            studio_logging.logging.getLogger('app').removeHandler(handler)
            handler.close()
