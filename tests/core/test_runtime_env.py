from pathlib import Path
import os


def test_windows_runtime_path_excludes_host_native_tools(monkeypatch):
    from app.core.runtime_env import configure_native_environment
    monkeypatch.setattr('sys.platform', 'win32')
    monkeypatch.setattr('sys.executable', 'D:/studio/.venv/Scripts/python.exe')
    monkeypatch.setenv('SystemRoot', 'C:/Windows')
    monkeypatch.setenv('PATH', 'D:/unrelated/poppler;D:/unrelated/openssl')
    configure_native_environment()
    parts = os.environ['PATH'].split(os.pathsep)
    assert parts == [str(Path('D:/studio/.venv/Scripts')), str(Path('C:/Windows/System32')), str(Path('C:/Windows'))]
    assert 'poppler' not in os.environ['PATH']
    assert 'openssl' not in os.environ['PATH']


def test_non_windows_environment_is_unchanged(monkeypatch):
    from app.core.runtime_env import configure_native_environment
    monkeypatch.setattr('sys.platform', 'linux')
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    configure_native_environment()
    assert os.environ['PATH'] == '/usr/bin:/bin'
