import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.cancel import CancelToken
from app.errors import Cancelled, ContentInvalid, DownloadFailed
from app.services.tiktok import probe, updater
from app.services.tiktok._process import run_process


def probe_json(**stream_overrides):
    stream = {'codec_type': 'video', 'codec_name': 'h264', 'width': 720, 'height': 1280,
              'nb_read_frames': '75', 'duration': '2.5'} | stream_overrides
    return json.dumps({'streams': [stream], 'format': {'duration': '2.5', 'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'}})


@pytest.fixture
def media(tmp_path, monkeypatch):
    path = tmp_path / '123.mp4'
    path.write_bytes(b'example-video-bytes')
    monkeypatch.setattr(probe, 'local_tool', Mock(return_value=tmp_path / 'ffprobe.exe'))
    run = Mock(return_value=probe_json())
    monkeypatch.setattr(probe, 'run_process', run)
    return path, run


def test_probe_duration_dimensions_hash_and_frame_scan(media):
    path, run = media
    result = probe.probe_video(path)
    assert (result.duration, result.width, result.height, result.size) == (2.5, 720, 1280, 19)
    assert result.sha256 == hashlib.sha256(b'example-video-bytes').hexdigest()
    command = run.call_args.args[0]
    assert '-count_frames' in command
    assert command[command.index('-protocol_whitelist') + 1] == 'file'


@pytest.mark.parametrize('output', ['not json', '{}', probe_json(nb_read_frames='0'), probe_json(width=0),
                                  probe_json(codec_name='unknown'), probe_json(duration='NaN')])
def test_probe_invalid_or_undecodable_file(media, output):
    path, run = media
    run.return_value = output
    with pytest.raises(ContentInvalid):
        probe.probe_video(path)


def test_probe_missing_file_and_precancelled(media, tmp_path):
    path, run = media
    with pytest.raises(ContentInvalid):
        probe.probe_video(tmp_path / 'missing.mp4')
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        probe.probe_video(path, cancel_token=token)
    run.assert_not_called()


def test_missing_binary_is_explicit_and_never_downloads(monkeypatch, tmp_path):
    from app.services.tiktok import _process
    monkeypatch.setattr(_process, 'project_root', lambda: tmp_path)
    with pytest.raises(DownloadFailed) as caught:
        _process.local_tool('ffprobe')
    assert 'bin' in caught.value.user_message and 'ffmpeg' in caught.value.user_message
    assert not caught.value.retryable
    assert not list(tmp_path.iterdir())


def test_process_cancellation_kills_child_and_no_console(monkeypatch):
    from app.services.tiktok import _process
    token = CancelToken()
    process = Mock(returncode=0)
    process.poll.return_value = None
    def communicate(timeout):
        token.cancel()
        raise subprocess.TimeoutExpired('ffprobe', timeout)
    calls = 0
    def communicate_cancel(timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return communicate(timeout)
        return '', ''
    process.communicate.side_effect = communicate_cancel
    factory = Mock(return_value=process)
    monkeypatch.setattr(_process.subprocess, 'Popen', factory)
    with pytest.raises(Cancelled):
        run_process(['ffprobe.exe', 'test.mp4'], cancel_token=token)
    process.kill.assert_called_once()
    process.communicate.assert_called()
    assert factory.call_args.kwargs['shell'] is False
    assert factory.call_args.kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW


def test_process_errors_and_timeout_are_not_retried(monkeypatch):
    from app.services.tiktok import _process
    process = Mock(returncode=1)
    process.communicate.return_value = ('', 'raw signed URL must not leak')
    monkeypatch.setattr(_process.subprocess, 'Popen', Mock(return_value=process))
    with pytest.raises(DownloadFailed) as caught:
        run_process(['ffprobe.exe'])
    assert 'raw signed' not in str(caught.value) + caught.value.user_message
    assert not caught.value.retryable


def test_updater_requires_explicit_click(monkeypatch):
    run = Mock()
    monkeypatch.setattr(updater, 'run_process', run)
    assert updater.get_ytdlp_version()
    with pytest.raises(ContentInvalid):
        updater.update_ytdlp()
    run.assert_not_called()


def test_updater_only_targets_project_venv_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, 'project_root', lambda: tmp_path)
    interpreter = tmp_path / '.venv/Scripts/python.exe'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b'fake interpreter')
    run = Mock(return_value='')
    monkeypatch.setattr(updater, 'run_process', run)
    message = updater.update_ytdlp(user_requested=True)
    command = run.call_args.args[0]
    assert command[0] == str(interpreter)
    assert command[-1] == 'yt-dlp'
    assert '--upgrade' in command and '--no-user' in command and '--require-virtualenv' in command
    assert '--isolated' in command and '--no-deps' in command
    assert Path(command[command.index('--cache-dir') + 1]).is_relative_to(tmp_path)
    environment = run.call_args.kwargs['env']
    for key in ('TEMP', 'TMP', 'PIP_CACHE_DIR', 'PYTHONPYCACHEPREFIX'):
        assert Path(environment[key]).is_relative_to(tmp_path)
    assert 'khởi động lại' in message.lower()


def test_updater_disables_inherited_pip_file_config(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(updater, 'project_root', lambda: tmp_path)
    interpreter = tmp_path / '.venv/Scripts/python.exe'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b'fake interpreter')
    monkeypatch.setenv('PIP_CONFIG_FILE', 'C:\\outside\\pip.ini')
    run = Mock(return_value='')
    monkeypatch.setattr(updater, 'run_process', run)
    updater.update_ytdlp(user_requested=True)
    assert run.call_args.kwargs['env']['PIP_CONFIG_FILE'] == os.devnull
    command = run.call_args.args[0]
    assert any(arg.startswith('pycache_prefix=') for arg in command)


def test_updater_missing_venv_does_not_use_global_python(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, 'project_root', lambda: tmp_path)
    run = Mock()
    monkeypatch.setattr(updater, 'run_process', run)
    with pytest.raises(DownloadFailed):
        updater.update_ytdlp(user_requested=True)
    run.assert_not_called()


def test_process_environment_cannot_redirect_temp_build_tracker_or_ffmpeg_log(monkeypatch, tmp_path):
    from app.services.tiktok._process import project_environment
    monkeypatch.setenv('TMPDIR', 'C:\\outside\\temp')
    monkeypatch.setenv('PIP_BUILD_TRACKER', 'C:\\outside\\tracker')
    monkeypatch.setenv('FFREPORT', 'file=C:/outside/report.log')
    environment = project_environment(tmp_path)
    assert Path(environment['TMPDIR']).is_relative_to(tmp_path)
    assert 'PIP_BUILD_TRACKER' not in environment
    assert 'FFREPORT' not in environment
