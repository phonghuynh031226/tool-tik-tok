import json
from pathlib import Path
import sys

import pytest

from app.core.paths import default_download_directory, project_root, resolve_download_directory
from app.security.settings import JSONSettingsStore


def test_default_ignores_temp_and_current_directory(monkeypatch, tmp_path):
    root = project_root()
    monkeypatch.setenv('TEMP', str(root / '.tmp'))
    monkeypatch.setenv('TMP', str(root / '.tmp'))
    monkeypatch.chdir(tmp_path)
    assert default_download_directory() == root / 'downloads'
    assert JSONSettingsStore(tmp_path / 'settings.json').get('download_dir') == str(root / 'downloads')


def test_frozen_default_uses_executable_not_bundle_or_temp(monkeypatch, tmp_path):
    temporary = tmp_path / '.tmp'
    temporary.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'Studio.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(temporary / 'bundle'), raising=False)
    monkeypatch.setenv('TEMP', str(temporary))
    monkeypatch.setenv('TMP', str(temporary))
    monkeypatch.chdir(temporary)
    assert default_download_directory() == tmp_path / 'downloads'
    assert resolve_download_directory(Path('.tmp/downloads')) == tmp_path / 'downloads'
    assert JSONSettingsStore(tmp_path / 'settings.json').get('download_dir') == str(tmp_path / 'downloads')


@pytest.mark.parametrize('absolute', [False, True])
def test_legacy_setting_is_normalized_without_rewriting_file(monkeypatch, tmp_path, absolute):
    root = project_root()
    path = tmp_path / 'settings.json'
    legacy = str(root / '.tmp/downloads') if absolute else '.tmp/downloads'
    original = json.dumps({'download_dir': legacy})
    path.write_text(original, encoding='utf-8')
    monkeypatch.setenv('TEMP', str(root / '.tmp'))
    monkeypatch.setenv('TMP', str(root / '.tmp'))
    settings = JSONSettingsStore(path)
    assert settings.get('download_dir') == str(root / 'downloads')
    assert path.read_text(encoding='utf-8') == original
    settings.set('download_dir', legacy)
    assert settings.get('download_dir') == str(root / 'downloads')


def test_explicit_custom_directory_is_preserved(tmp_path):
    custom = tmp_path / 'chosen-downloads'
    assert resolve_download_directory(custom) == custom
    settings = JSONSettingsStore(tmp_path / 'settings.json')
    settings.set('download_dir', str(custom))
    assert settings.get('download_dir') == str(custom)
    assert not custom.exists()
