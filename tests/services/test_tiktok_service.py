from pathlib import Path
from unittest.mock import Mock

import pytest
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError

from app.contracts import DownloadResult, TikTokService as ServiceProtocol, VideoMeta
from app.core.cancel import CancelToken
from app.errors import Cancelled, ContentInvalid, DownloadFailed, NetworkError
from app.services.tiktok.service import TikTokService

URL = 'https://www.tiktok.com/@demo/video/123'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('urllib.request.OpenerDirector.open', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr('socket.create_connection', Mock(side_effect=AssertionError('Network forbidden')))


@pytest.fixture
def sdk(monkeypatch):
    from app.services.tiktok import service
    instance = Mock()
    instance.__enter__ = Mock(return_value=instance)
    instance.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=instance)
    monkeypatch.setattr(service.yt_dlp, 'YoutubeDL', factory)
    monkeypatch.setattr(service, 'local_tool', Mock(return_value=Path('ffmpeg.exe')))
    probe = Mock(side_effect=lambda path, **kwargs: DownloadResult(path, 5, 'abc', 2.5, 720, 1280))
    monkeypatch.setattr(service, 'probe_video', probe)
    return instance, factory, probe


def meta():
    return VideoMeta('123', URL, 'Title', 'Desc', 'Demo', None, 2.5, 720, 1280)


def test_metadata_parsing_and_no_download(sdk):
    instance, factory, _ = sdk
    instance.extract_info.return_value = {'id': '123', 'title': 'Title', 'description': 'Desc',
        'uploader': 'Demo', 'thumbnail': 'https://cdn.test/thumb.jpg', 'duration': 2.5, 'width': 720, 'height': 1280}
    service = TikTokService()
    assert isinstance(service, ServiceProtocol)
    result = service.fetch_metadata(URL + '?tracking=1')
    assert (result.video_id, result.url, result.author, result.width) == ('123', URL, 'Demo', 720)
    instance.extract_info.assert_called_once_with(URL, download=False)
    options = factory.call_args.args[0]
    assert options['noplaylist'] and options['geo_bypass'] is False
    assert options['allow_unplayable_formats'] is False


def test_metadata_missing_fields_and_dimensions_from_formats(sdk):
    instance, _, _ = sdk
    instance.extract_info.return_value = {'id': '123', 'formats': [{'width': 720, 'height': 1280}]}
    result = TikTokService().fetch_metadata(URL)
    assert result.title and result.description == '' and result.author == ''
    assert (result.width, result.height, result.duration, result.thumbnail_url) == (720, 1280, None, None)


@pytest.mark.parametrize('info', [None, {'id': '456'}, {'id': '123', '_type': 'playlist', 'entries': []},
    {'id': '123', 'is_live': True}, {'id': '123', 'has_drm': True}])
def test_bad_metadata_rejected(sdk, info):
    sdk[0].extract_info.return_value = info
    with pytest.raises(ContentInvalid):
        TikTokService().fetch_metadata(URL)


@pytest.mark.parametrize(('error', 'message'), [
    (DownloadError('This video is private'), 'riêng tư'),
    (GeoRestrictedError('Not available in your country'), 'khu vực'),
    (DownloadError('Login to confirm your age; age-restricted'), 'tuổi'),
    (DownloadError('This video has been deleted'), 'xóa'),
    (DownloadError('HTTP Error 404: Not Found'), 'xóa'),
    (DownloadError('Unsupported DRM protected video'), 'DRM'),
])
def test_permanent_errors_have_clear_messages_and_no_retry(sdk, error, message):
    sdk[0].extract_info.side_effect = error
    with pytest.raises(DownloadFailed) as caught:
        TikTokService().fetch_metadata(URL)
    assert message in caught.value.user_message
    assert not caught.value.retryable
    assert sdk[0].extract_info.call_count == 1


def test_unknown_extractor_error_not_retried(sdk):
    sdk[0].extract_info.side_effect = ExtractorError('Unable to extract new TikTok schema')
    with pytest.raises(DownloadFailed) as caught:
        TikTokService().fetch_metadata(URL)
    assert not caught.value.retryable
    assert sdk[0].extract_info.call_count == 1


def test_transient_retry_at_most_three_times(sdk, monkeypatch):
    from app.services.tiktok import service as module
    waits = Mock()
    monkeypatch.setattr(module, 'wait_backoff', waits)
    sdk[0].extract_info.side_effect = DownloadError('HTTP Error 503: Service Unavailable')
    with pytest.raises(NetworkError):
        TikTokService().fetch_metadata(URL)
    assert sdk[0].extract_info.call_count == 4
    assert [call.args[0] for call in waits.call_args_list] == [1.0, 2.0, 4.0]


def test_transient_retry_then_success(sdk, monkeypatch):
    monkeypatch.setattr('app.services.tiktok.service.wait_backoff', Mock())
    sdk[0].extract_info.side_effect = [DownloadError('Connection reset by peer'), {'id': '123'}]
    assert TikTokService().fetch_metadata(URL).video_id == '123'
    assert sdk[0].extract_info.call_count == 2


def downloading_sdk(sdk, *, on_hook=None):
    instance, factory, _ = sdk

    def extract(url, download):
        options = factory.call_args.args[0]
        hook = options['progress_hooks'][0]
        hook({'status': 'downloading', 'downloaded_bytes': 5, 'total_bytes': 10, 'speed': 1234, 'eta': 1})
        if on_hook:
            on_hook()
        hook({'status': 'finished', 'downloaded_bytes': 10, 'total_bytes': 10})
        Path(options['outtmpl'].replace('%(ext)s', 'mp4')).write_bytes(b'video')
        return {'id': '123'}

    instance.extract_info.side_effect = extract


def test_download_mp4_progress_and_verified_result(sdk, tmp_path):
    downloading_sdk(sdk)
    progress, details = [], []
    service = TikTokService(on_details=details.append)
    result = service.download(meta(), tmp_path, progress.append, CancelToken())
    assert result.path == tmp_path / '123.mp4'
    assert result.path.read_bytes() == b'video'
    assert result.sha256 == 'abc'
    assert progress[0] == 0 and progress[-1] == 1 and progress == sorted(progress)
    assert any(item.speed_bytes_per_second == 1234 and item.downloaded_bytes == 5 and item.total_bytes == 10 for item in details)
    assert details[-1].phase == 'complete'
    assert not list(tmp_path.glob('.123-*'))
    options = sdk[1].call_args.args[0]
    assert options['retries'] == options['fragment_retries'] == options['extractor_retries'] == 0
    assert '[ext=mp4]' in options['format']
    assert 'watermark' not in options['format'].lower()


def test_download_uses_single_direct_mp4_without_blocking_sdk_merge(sdk, tmp_path):
    downloading_sdk(sdk)
    TikTokService().download(meta(), tmp_path, lambda value: None, CancelToken())
    options = sdk[1].call_args.args[0]
    assert '+' not in options['format']
    assert '[protocol=https]' in options['format']
    assert '[protocol=http]' in options['format']
    assert options['fixup'] == 'never'


def test_download_transient_retry_cleans_partial_then_succeeds(sdk, tmp_path, monkeypatch):
    monkeypatch.setattr('app.services.tiktok.service.wait_backoff', Mock())
    downloading_sdk(sdk)
    successful_download = sdk[0].extract_info.side_effect
    calls = 0
    stages = []
    def flaky(url, download):
        nonlocal calls
        calls += 1
        options = sdk[1].call_args.args[0]
        path = Path(options['outtmpl'].replace('%(ext)s', 'mp4'))
        stages.append(path.parent)
        if calls == 1:
            path.write_bytes(b'partial')
            raise DownloadError('HTTP Error 502: Bad Gateway')
        assert not stages[0].exists()
        return successful_download(url, download)
    sdk[0].extract_info.side_effect = flaky
    assert TikTokService().download(meta(), tmp_path, lambda value: None, CancelToken()).path.read_bytes() == b'video'
    assert calls == 2 and stages[0] != stages[1]


def test_ssl_urlerror_is_not_temporary():
    import ssl
    from urllib.error import URLError
    from app.services.tiktok.errors import map_error
    error = map_error(URLError(ssl.SSLCertVerificationError('certificate verify failed')))
    assert isinstance(error, DownloadFailed) and not error.retryable
    assert 'TLS' in error.user_message


def test_valid_existing_file_skips_ydl(sdk, tmp_path):
    target = tmp_path / '123.mp4'
    target.write_bytes(b'video')
    progress = []
    assert TikTokService().download(meta(), tmp_path, progress.append, CancelToken()).path == target
    sdk[1].assert_not_called()
    assert progress[-1] == 1


@pytest.mark.parametrize('absolute', [False, True])
def test_legacy_default_goes_to_downloads_and_preserves_old_file(sdk, tmp_path, monkeypatch, absolute):
    import sys
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'studio.exe'))
    temporary = tmp_path / '.tmp'
    legacy = temporary / 'downloads'
    legacy.mkdir(parents=True)
    old_file = legacy / '123.mp4'
    old_file.write_bytes(b'old-user-file-do-not-touch')
    monkeypatch.setenv('TEMP', str(temporary))
    monkeypatch.setenv('TMP', str(temporary))
    monkeypatch.chdir(temporary)
    downloading_sdk(sdk)
    destination = legacy if absolute else Path('.tmp/downloads')
    result = TikTokService().download(meta(), destination, lambda value: None, CancelToken())
    assert result.path == tmp_path / 'downloads/123.mp4'
    assert result.path.read_bytes() == b'video'
    assert old_file.read_bytes() == b'old-user-file-do-not-touch'


def test_invalid_existing_file_is_replaced_only_after_validation(sdk, tmp_path):
    target = tmp_path / '123.mp4'
    target.write_bytes(b'broken')
    sdk[2].side_effect = [ContentInvalid(), DownloadResult(target, 5, 'abc', 2.5, 720, 1280)]
    downloading_sdk(sdk)
    TikTokService().download(meta(), tmp_path, lambda value: None, CancelToken())
    assert target.read_bytes() == b'video'


def test_invalid_download_preserves_existing_file(sdk, tmp_path):
    target = tmp_path / '123.mp4'
    target.write_bytes(b'old')
    sdk[2].side_effect = ContentInvalid()
    downloading_sdk(sdk)
    with pytest.raises(ContentInvalid):
        TikTokService().download(meta(), tmp_path, lambda value: None, CancelToken())
    assert target.read_bytes() == b'old'
    assert sdk[0].extract_info.call_count == 1
    assert not list(tmp_path.glob('.123-*'))


def test_cancel_mid_download_no_retry_or_final_file(sdk, tmp_path):
    token = CancelToken()
    downloading_sdk(sdk, on_hook=token.cancel)
    with pytest.raises(Cancelled):
        TikTokService().download(meta(), tmp_path, lambda value: None, token)
    assert sdk[0].extract_info.call_count == 1
    assert not list(tmp_path.iterdir())


def test_precancelled_does_not_touch_sdk(sdk, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        TikTokService().download(meta(), tmp_path, lambda value: None, token)
    sdk[1].assert_not_called()


def test_callback_error_propagates_without_retry(sdk, tmp_path):
    downloading_sdk(sdk)
    def broken_callback(value):
        if value > 0:
            raise RuntimeError('UI callback failed')
    with pytest.raises(RuntimeError, match='UI callback failed'):
        TikTokService().download(meta(), tmp_path, broken_callback, CancelToken())
    assert sdk[0].extract_info.call_count == 1


def test_mismatched_or_unsafe_video_id_rejected_before_sdk(sdk, tmp_path):
    item = meta()
    item.video_id = '../escape'
    with pytest.raises(ContentInvalid):
        TikTokService().download(item, tmp_path, lambda value: None, CancelToken())
    sdk[1].assert_not_called()


def test_cancel_during_backoff(sdk, monkeypatch, tmp_path):
    token = CancelToken()
    def cancel_wait(delay, cancel_token):
        token.cancel()
        token.raise_if_cancelled()
    monkeypatch.setattr('app.services.tiktok.service.wait_backoff', cancel_wait)
    sdk[0].extract_info.side_effect = DownloadError('HTTP Error 503: Service Unavailable')
    with pytest.raises(Cancelled):
        TikTokService().download(meta(), tmp_path, lambda value: None, token)
    assert sdk[0].extract_info.call_count == 1
    assert not list(tmp_path.iterdir())
