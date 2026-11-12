import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.paths import project_root, resource_root, safe_path


def test_source_root_does_not_depend_on_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert project_root() == Path(__file__).resolve().parents[2]


def test_frozen_roots(monkeypatch, tmp_path):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'studio.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    assert project_root() == tmp_path
    assert resource_root() == bundle


def test_frozen_without_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'studio.exe'))
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    assert resource_root() == tmp_path


def test_normalizes_without_creating_files(tmp_path):
    assert safe_path('downloads', '..', 'data', 'new.db', root=tmp_path) == tmp_path / 'data/new.db'
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('relative', ['../escape', '../../escape'])
def test_rejects_traversal(tmp_path, relative):
    with pytest.raises(ValueError):
        safe_path(relative, root=tmp_path)


def test_rejects_absolute_outside_and_similar_prefix(tmp_path):
    for outside in [tmp_path.parent / 'outside', Path(str(tmp_path) + '-other')]:
        with pytest.raises(ValueError):
            safe_path(outside, root=tmp_path)


def test_rejects_symlink_if_supported(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('Windows không cấp quyền tạo symlink; junction được kiểm tra riêng.')
    with pytest.raises(ValueError):
        safe_path('link/file.mp4', root=tmp_path)
    with pytest.raises(ValueError):
        safe_path('link/../file.mp4', root=tmp_path)
    with pytest.raises(ValueError):
        safe_path('file.mp4', root=link)


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction')
def test_rejects_windows_junction(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'junction'
    # Native single-shell operation; targets stay within pytest's project-local temp.
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    try:
        with pytest.raises(ValueError):
            safe_path('junction/video.mp4', root=tmp_path)
        with pytest.raises(ValueError):
            safe_path('junction/../video.mp4', root=tmp_path)
        with pytest.raises(ValueError):
            safe_path('video.mp4', root=link)
    finally:
        link.rmdir()  # Removes only the junction, never the target tree.
