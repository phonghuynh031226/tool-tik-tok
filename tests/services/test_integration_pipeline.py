import json
from unittest.mock import Mock

from tests.services.test_tiktok_service import sdk, downloading_sdk, URL
from tests.services.test_youtube_service import setup_service
from app.core.cancel import CancelToken
from app.contracts import UploadRequest
from app.db.repository import SQLiteHistoryRepository
from app.security.settings import JSONSettingsStore
from app.services.gemini.generator import GeminiContentGenerator
from app.services.tiktok.service import TikTokService
from app.ui.services import ServiceContainer
from app.ui.main_window import MainWindow


def test_real_services_mock_end_to_end(sdk, setup_service, tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", Mock(side_effect=AssertionError("History save failed")))
    youtube, _, upload_sdk, _, secrets, _ = setup_service
    from app.contracts import DownloadResult
    sdk[2].side_effect = lambda path, **kwargs: DownloadResult(path, 5, 'a' * 64, 2.5, 720, 1280)
    tiktok = TikTokService()
    sdk[0].extract_info.return_value = {'id': '123', 'title': 'Source', 'description': 'Description'}
    meta = tiktok.fetch_metadata(URL)
    downloading_sdk(sdk)
    download = tiktok.download(meta, tmp_path / 'downloads', lambda p: None, CancelToken())
    client = Mock()
    client.models.generate_content.return_value.text = json.dumps({
        'title': 'Generated title', 'description': 'Generated description',
        'hashtags': ['shorts'], 'tags': ['demo']})
    generator = GeminiContentGenerator(api_key='mock-only', client_factory=lambda _: client)
    content = generator.generate(meta, {})
    history = SQLiteHistoryRepository(tmp_path / 'history.db', secret_store=secrets)
    try:
        container = ServiceContainer(tiktok, generator, youtube, history, secrets,
                                     JSONSettingsStore(tmp_path / 'settings.json'))
        window = MainWindow(container)
        qtbot.addWidget(window)
        state = window.job_state
        state.meta = meta
        state.set_download_result(download)
        state.title = content.title
        state.description = content.description
        state.tags = content.tags
        state.made_for_kids = False
        state.rights_confirmed = True
        req = state.build_upload_request()
        channel = youtube.get_channel()
        youtube.confirm_upload(req, made_for_kids=False, channel_id=channel.id)
        result = youtube.upload(req, lambda p: None, CancelToken())
        from app.ui.pages.youtube_page import YouTubePage
        page = window.findChild(YouTubePage)
        page._on_finished(result)
        record = history.find_by_video_id(meta.video_id)
        assert record['youtube_video_id'] == result.video_id
        assert record['youtube_title'] == content.title
        assert record['sha256'] == download.sha256
        assert len(history.list()) == 1
        assert upload_sdk.next_chunk.call_count == 1
    finally:
        history.close()
