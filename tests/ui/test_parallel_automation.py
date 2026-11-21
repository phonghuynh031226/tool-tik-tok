import threading
import pytest
from app.contracts import GeneratedContent
from tests.ui.test_automation_ui import configured, start


@pytest.mark.parametrize('first', ['ai', 'download'])
def test_metadata_generation_overlaps_download_and_upload_waits_for_both(qtbot, tmp_path, first):
    window, services = configured(qtbot, tmp_path)
    download_started, ai_started = threading.Event(), threading.Event()
    download_release, ai_release = threading.Event(), threading.Event()
    download = services.tiktok.download.side_effect
    def slow_download(*args, **kwargs):
        download_started.set()
        assert download_release.wait(8)
        return download(*args, **kwargs)
    def slow_ai(meta, settings, **kwargs):
        ai_started.set()
        assert ai_release.wait(8)
        return GeneratedContent('Parallel AI title', 'AI description', [], [])
    services.tiktok.download.side_effect = slow_download
    services.generator.generate.side_effect = slow_ai
    try:
        start(window, services)
        qtbot.waitUntil(lambda: download_started.is_set() and ai_started.is_set(), timeout=3000)
        services.youtube.upload.assert_not_called()
        (ai_release if first == 'ai' else download_release).set()
        if first == 'ai':
            qtbot.waitUntil(lambda: window.job_state.content is not None)
        else:
            qtbot.waitUntil(lambda: window.job_state.local_video_path is not None)
        services.youtube.upload.assert_not_called()
        assert window.automation.busy
        download_release.set(); ai_release.set()
        qtbot.waitUntil(lambda: not window.automation.busy, timeout=5000)
        services.youtube.upload.assert_called_once()
        request = services.youtube.upload.call_args.args[0]
        assert request.title == 'Parallel AI title' and request.path.exists()
        assert services.automation_store.list_jobs()[0]['status'] == 'done'
        assert services.history.list()[0]['youtube_video_id'] == 'v'*11
    finally:
        download_release.set(); ai_release.set()
        window.automation.deactivate()


def test_files_api_generation_waits_for_completed_download(qtbot, tmp_path):
    window, services = configured(qtbot, tmp_path)
    services.settings.set('analyze_video_file', True)
    downloading, release = threading.Event(), threading.Event()
    download = services.tiktok.download.side_effect
    def blocked(*args, **kwargs):
        downloading.set(); assert release.wait(8)
        return download(*args, **kwargs)
    services.tiktok.download.side_effect = blocked
    try:
        start(window, services)
        qtbot.waitUntil(downloading.is_set, timeout=3000)
        qtbot.wait(100)
        services.generator.generate.assert_not_called()
        release.set()
        qtbot.waitUntil(lambda: not window.automation.busy, timeout=5000)
        settings = services.generator.generate.call_args.args[1]
        from pathlib import Path
        assert Path(settings['video_path']).exists()
        assert settings['analyze_video_file'] is True
        services.youtube.upload.assert_called_once()
    finally:
        release.set()
        window.automation.deactivate()


def test_stop_cancels_both_branches_and_discards_late_results(qtbot, tmp_path):
    window, services = configured(qtbot, tmp_path)
    downloading, generating, release = threading.Event(), threading.Event(), threading.Event()
    tokens = []
    download = services.tiktok.download.side_effect
    def blocked_download(*args, **kwargs):
        tokens.append(kwargs['cancel_token']); downloading.set(); release.wait(8)
        return download(*args, **kwargs)
    def blocked_ai(meta, settings, **kwargs):
        generating.set(); release.wait(8)
        return GeneratedContent('Late AI title', 'Late description', [], [])
    services.tiktok.download.side_effect = blocked_download
    services.generator.generate.side_effect = blocked_ai
    try:
        start(window, services)
        qtbot.waitUntil(lambda: downloading.is_set() and generating.is_set(), timeout=3000)
        ai_worker = window.page_dashboard._active_ai_worker
        window.automation.deactivate()
        qtbot.waitUntil(lambda: not window.automation.busy, timeout=2000)
        assert tokens[0].is_cancelled and ai_worker.cancel_token.is_cancelled
        assert window.page_dashboard.input_url.isEnabled()
        release.set()
        from app.workers.base import background_requests
        qtbot.waitUntil(lambda: not background_requests(), timeout=250)
        services.youtube.upload.assert_not_called()
        assert window.job_state.content is None
        assert window.job_state.local_video_path is None
        assert services.automation_store.list_jobs()[0]['status'] == 'cancelled'
    finally:
        release.set()
        window.automation.deactivate()

