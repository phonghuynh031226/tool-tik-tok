# -*- mode: python ; coding: utf-8 -*-
"""One-directory, windowed Windows bundle. Only code/package data + safe assets.

Never add the project root, config, data, downloads, logs or a selected OAuth file
as a data directory. ffmpeg/ffprobe are copied explicitly by build.bat afterwards.
"""
from pathlib import Path
import fnmatch
import stat

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).resolve()


def blocked(path):
    name = Path(path).name.lower()
    return (fnmatch.fnmatch(name, 'client_secret*') or name.startswith('token')
            or name.endswith(('.db', '.db-wal', '.db-shm', '.db-journal', '.sqlite', '.sqlite3', '.mp4')))


datas = collect_data_files('googleapiclient', includes=['discovery_cache/documents/youtube.v3.json'])
hidden = ['PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
          'keyring.backends.Windows', 'yt_dlp.extractor.tiktok']
hidden += collect_submodules('app', filter=lambda name: name != 'app.services.fakes')
hidden += collect_submodules('google.genai')
binaries = collect_dynamic_libs('PySide6')

assets = root / 'assets'
if assets.exists():
    for item in assets.rglob('*'):
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Asset links/junctions are not permitted in a distributable.')
        if item.is_file() and item.suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.ico', '.webp', '.ttf', '.otf'}:
            if not blocked(item):
                datas.append((str(item), str(item.parent.relative_to(root))))

a = Analysis(
    [str(root / 'main.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pytest', 'pytestqt', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'app.services.fakes'],
    noarchive=False,
)

# Reject forbidden files even if a dependency hook unexpectedly collects them.
for toc in (a.datas, a.binaries):
    for destination, source, kind in toc:
        if blocked(destination) or blocked(source):
            raise ValueError('Forbidden credential/database/video data in bundle TOC.')
        source_path = Path(source).resolve()
        if source_path.is_relative_to(root):
            relative = source_path.relative_to(root)
            if relative.parts and relative.parts[0].lower() in {'config', 'data', 'downloads', 'logs', '.aws'}:
                raise ValueError('Private project data must not be bundled.')

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TikTokYouTubeStudio',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TikTokYouTubeStudio')
