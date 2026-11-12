import pytest

from app.contracts import JobStatus, UploadRequest
from app.core.cancel import CancelToken
from app.errors import AuthExpired, Cancelled, ContentInvalid
from app.services.fakes import (
    FakeContentGenerator, FakeHistoryRepository, FakeSecretStore,
    FakeSettingsStore, FakeTikTokService, FakeYouTubeService,
)


def test_fake_preview_flow_has_progress_and_no_disk_or_network(tmp_path):
    service = FakeTikTokService()
    meta = service.fetch_metadata('https://www.tiktok.com/@demo/video/123')
    progress = []
    result = service.download(meta, tmp_path, progress.append, CancelToken())
    assert result.path == tmp_path / 'demo-001.mp4'
    assert progress == [0.0, 0.5, 1.0]
    assert not result.path.exists()  # Placeholder, deliberately not a valid MP4.
    generator = FakeContentGenerator()
    assert generator.test_connection()
    assert generator.list_models() == ['fake-gemini-dev']
    content = generator.generate(meta, {})
    youtube = FakeYouTubeService()
    with pytest.raises(AuthExpired):
        youtube.get_channel()
    channel = youtube.connect()
    request = UploadRequest(result.path, content.title, content.description, content.tags)
    with pytest.raises(ContentInvalid):
        youtube.upload(request, progress.append, CancelToken())
    request.rights_confirmed = True
    progress.clear()
    uploaded = youtube.upload(request, progress.append, CancelToken())
    assert uploaded.channel_id == channel.id
    assert progress == [0.0, 0.5, 1.0]
    assert youtube.check_processing(uploaded.video_id) == 'succeeded'
    youtube.disconnect()
    with pytest.raises(AuthExpired):
        youtube.get_channel()


def test_fake_download_stops_when_callback_cancels(tmp_path):
    token = CancelToken()
    service = FakeTikTokService()
    meta = service.fetch_metadata('demo')
    progress = []

    def cancel_at_start(value):
        progress.append(value)
        token.cancel()

    with pytest.raises(Cancelled):
        service.download(meta, tmp_path, cancel_at_start, token)
    assert progress == [0.0]
    assert not list(tmp_path.iterdir())


def test_fake_upload_honors_precancelled_token(tmp_path):
    service = FakeYouTubeService()
    service.connect()
    token = CancelToken()
    token.cancel()
    request = UploadRequest(tmp_path / 'sample.mp4', 'Title', 'Description', [], rights_confirmed=True)
    with pytest.raises(Cancelled):
        service.upload(request, lambda value: None, token)


def test_fake_history_and_stores_are_isolated_in_memory():
    history = FakeHistoryRepository()
    job_id = history.add({'video_id': 'demo-001', 'sha256': 'abc', 'title': 'Demo', 'status': JobStatus.NEW})
    history.update(job_id, {'status': JobStatus.CONTENT_READY})
    assert history.find_by_video_id('demo-001')['status'] == JobStatus.CONTENT_READY
    assert history.find_by_hash('abc')['id'] == job_id
    assert history.find_by_hash('missing') is None
    assert history.search('demo')[0]['id'] == job_id
    assert history.list(status=JobStatus.NEW) == []
    assert history.list(limit=1, offset=1) == []
    copied = history.list()[0]
    copied['title'] = 'changed'
    assert history.list()[0]['title'] == 'Demo'
    assert FakeHistoryRepository().list() == []
    with pytest.raises(KeyError):
        history.update(999, {})
    secret = FakeSecretStore()
    assert secret.get('key') is None
    secret.set('key', 'dev-value')
    assert secret.get('key') == 'dev-value'
    secret.delete('key')
    secret.delete('key')
    assert secret.get('key') is None
    settings = FakeSettingsStore()
    assert settings.get('privacy', 'private') == 'private'
    settings.set('privacy', 'unlisted')
    assert settings.get('privacy') == 'unlisted'


def test_fake_history_lookup_is_not_limited_to_first_page():
    history = FakeHistoryRepository()
    history.add({'video_id': 'oldest', 'sha256': 'old-hash'})
    for index in range(101):
        history.add({'video_id': str(index), 'sha256': str(index)})
    assert history.find_by_video_id('oldest')['id'] == 1
    assert history.find_by_hash('old-hash')['id'] == 1
