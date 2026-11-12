from dataclasses import asdict, fields
from pathlib import Path
from typing import get_type_hints

import pytest

from app.contracts import (
    ChannelInfo, ContentGenerator, DownloadResult, GeneratedContent, HistoryRepository,
    JobStatus, SecretStore, SettingsStore, TikTokService, UploadRequest,
    UploadResult, VideoMeta, YouTubeService,
)
from app.core.cancel import CancelToken
from app.errors import (
    AppError, AuthExpired, Cancelled, ContentInvalid, DisallowedHost,
    DownloadFailed, InvalidUrl, NetworkError, QuotaExceeded,
)


def test_job_status_serialization():
    values = ['NEW', 'METADATA_OK', 'DOWNLOADED', 'CONTENT_READY', 'UPLOADING', 'UPLOADED', 'FAILED', 'CANCELLED']
    assert [JobStatus(value).value for value in values] == values


@pytest.mark.parametrize(('model', 'names'), [
    (VideoMeta, 'video_id url title description author thumbnail_url duration width height'),
    (DownloadResult, 'path size sha256 duration width height'),
    (GeneratedContent, 'title description hashtags tags'),
    (UploadRequest, 'path title description tags privacy made_for_kids category_id default_language rights_confirmed'),
    (UploadResult, 'video_id url channel_id'),
    (ChannelInfo, 'id title'),
])
def test_frozen_contract_field_layout(model, names):
    assert [field.name for field in fields(model)] == names.split()


def test_upload_defaults_require_user_confirmation():
    request = UploadRequest(Path('sample.mp4'), 'Tiêu đề', 'Mô tả', [])
    assert asdict(request)['rights_confirmed'] is False
    assert request.privacy == 'private'


def test_public_protocol_annotations_can_be_resolved():
    assert get_type_hints(TikTokService.download)['cancel_token'] is CancelToken
    assert get_type_hints(YouTubeService.upload)['return'] is UploadResult


def test_cancel_token():
    token = CancelToken()
    assert not token.is_cancelled
    token.raise_if_cancelled()
    token.cancel()
    token.cancel()
    assert token.is_cancelled
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()


@pytest.mark.parametrize('error_type', [AppError, InvalidUrl, DisallowedHost, DownloadFailed, Cancelled, QuotaExceeded, AuthExpired, NetworkError, ContentInvalid])
def test_errors_have_safe_vietnamese_messages(error_type):
    error = error_type('internal detail')
    assert isinstance(error, AppError)
    assert isinstance(error.retryable, bool)
    assert error.user_message and error.user_message != 'internal detail'


def test_fake_implementations_satisfy_protocols():
    from app.services.fakes import (
        FakeContentGenerator, FakeHistoryRepository, FakeSecretStore,
        FakeSettingsStore, FakeTikTokService, FakeYouTubeService,
    )
    for fake, protocol in [
        (FakeTikTokService(), TikTokService), (FakeContentGenerator(), ContentGenerator),
        (FakeYouTubeService(), YouTubeService), (FakeHistoryRepository(), HistoryRepository),
        (FakeSecretStore(), SecretStore), (FakeSettingsStore(), SettingsStore),
    ]:
        assert isinstance(fake, protocol)
