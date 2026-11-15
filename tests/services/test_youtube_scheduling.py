from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.contracts import JobStatus, UploadRequest
from app.core.cancel import CancelToken
from app.db.repository import SQLiteHistoryRepository
from app.errors import ContentInvalid, ScheduleInPast, Cancelled
from app.services.youtube import validators
from tests.services.test_youtube_service import setup_service, no_network, CHANNEL, VIDEO, http_error


@pytest.fixture
def scheduled(setup_service, tmp_path):
    youtube, req, request, api, secrets, _ = setup_service
    history = SQLiteHistoryRepository(tmp_path / 'schedule.db', secret_store=secrets)
    youtube._history_repository = history
    req.publish_at = datetime.now(timezone(timedelta(hours=7))) + timedelta(hours=2)
    req.privacy = 'public'
    youtube.confirm_upload(req, made_for_kids=False, channel_id=CHANNEL)
    yield youtube, req, request, api, history
    history.close()


def test_upload_body_utc_forced_private_and_scheduled_history(scheduled):
    youtube, req, _, api, history = scheduled
    result = youtube.upload(req, lambda _: None, CancelToken())
    status = api.videos.return_value.insert.call_args.kwargs['body']['status']
    assert status['privacyStatus'] == 'private'
    assert status['publishAt'] == req.publish_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    assert req.privacy == 'public'  # Caller-owned request is not silently edited.
    assert result.status == JobStatus.SCHEDULED
    row = history.list_scheduled()[0]
    assert row['channel_id'] == CHANNEL and row['youtube_video_id'] == VIDEO
    assert row['privacy_status'] == 'private' and row['uploaded_at'] is None
    assert datetime.fromisoformat(row['scheduled_at']) == req.publish_at
    # Replaying an already successful upload must not create another job/upload.
    assert youtube.upload(req, lambda _: None, CancelToken()).status == JobStatus.SCHEDULED
    assert len(history.list_scheduled()) == 1
    assert api.videos.return_value.insert.call_count == 1


@pytest.mark.parametrize('minutes', [-60, 0, 9])
def test_past_and_too_soon_are_rejected_before_api(setup_service, minutes):
    youtube, req, _, api, _, _ = setup_service
    req.publish_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    with pytest.raises(ScheduleInPast): youtube.upload(req, lambda _: None, CancelToken())
    api.videos.return_value.insert.assert_not_called()


@pytest.mark.parametrize('value', [datetime(2099, 1, 1), '2099-01-01', datetime.now(timezone.utc) + timedelta(days=366)])
def test_invalid_schedule_has_clear_validation(value, setup_service):
    youtube, req, _, api, _, _ = setup_service
    req.publish_at = value
    with pytest.raises(ContentInvalid): youtube.confirm_upload(req, made_for_kids=False, channel_id=CHANNEL)
    api.videos.return_value.insert.assert_not_called()


def test_schedule_minimum_boundary_uses_utc():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    target = now.astimezone(timezone(timedelta(hours=7))) + timedelta(minutes=10)
    assert validators.validate_publish_at(target, now=now) == now + timedelta(minutes=10)
    with pytest.raises(ScheduleInPast):
        validators.validate_publish_at(target - timedelta(microseconds=1), now=now)


def test_sync_requires_api_public_and_marks_overdue_private_for_review(scheduled):
    youtube, req, _, api, history = scheduled
    youtube.upload(req, lambda _: None, CancelToken())
    job = history.list_scheduled()[0]
    history.update(job['id'], {'scheduled_at': datetime.now(timezone.utc) - timedelta(minutes=1)})
    response = api.videos.return_value.list.return_value.execute
    response.return_value = {'items': [{'id': VIDEO, 'snippet': {'channelId': CHANNEL},
        'status': {'privacyStatus': 'private', 'uploadStatus': 'processed'}}]}
    assert youtube.sync_scheduled() == []
    row = history.get(job['id'])
    assert row['processing_status'] == JobStatus.SCHEDULED and row['uploaded_at'] is None
    assert row['schedule_needs_review'] is True and 'kiểm tra' in row['error_message'].lower()
    response.return_value['items'][0]['status']['privacyStatus'] = 'public'
    changes = youtube.sync_scheduled()
    assert len(changes) == 1 and changes[0].status == JobStatus.UPLOADED
    row = history.get(job['id'])
    assert row['status'] == JobStatus.UPLOADED and row['privacy_status'] == 'public'
    assert row['uploaded_at'] and row['schedule_needs_review'] is False
    assert history.list_scheduled() == [] and youtube.sync_scheduled() == []


@pytest.mark.parametrize('payload', [{'items': []}, {'items': [{'id': VIDEO,
    'snippet': {'channelId': 'UC' + 'b' * 22}, 'status': {'privacyStatus': 'public'}}]},
    {'items': [{'id': VIDEO, 'snippet': {'channelId': CHANNEL}, 'status': {'privacyStatus': 'unlisted'}}]}])
def test_sync_never_claims_public_for_missing_wrong_channel_or_unlisted(scheduled, payload):
    youtube, req, _, api, history = scheduled
    youtube.upload(req, lambda _: None, CancelToken())
    api.videos.return_value.list.return_value.execute.return_value = payload
    assert youtube.sync_scheduled() == []
    assert history.list_scheduled()[0]['uploaded_at'] is None


def test_sync_api_failure_retains_scheduled_and_safe_message(scheduled):
    youtube, req, _, api, history = scheduled
    youtube.upload(req, lambda _: None, CancelToken())
    api.videos.return_value.list.return_value.execute.side_effect = http_error(403, 'quotaExceeded')
    assert youtube.sync_scheduled() == []
    row = history.list_scheduled()[0]
    assert row['schedule_needs_review'] is True and row['uploaded_at'] is None


def test_scheduled_upload_without_valid_api_id_is_not_persisted(scheduled):
    youtube, req, request, _, history = scheduled
    request.next_chunk.return_value = (None, {'id': 'bad-id'})
    with pytest.raises(ContentInvalid): youtube.upload(req, lambda _: None, CancelToken())
    assert history.list_scheduled() == []


def test_cancel_after_api_acceptance_still_tracks_remote_schedule(scheduled):
    youtube, req, request, _, history = scheduled
    token = CancelToken()
    def accepted(**kwargs):
        token.cancel()
        return None, {'id': VIDEO, 'snippet': {'channelId': CHANNEL}}
    request.next_chunk.side_effect = accepted
    with pytest.raises(Cancelled): youtube.upload(req, lambda _: None, token)
    assert history.list_scheduled()[0]['youtube_video_id'] == VIDEO


def test_sync_future_private_does_not_claim_success_or_require_review(scheduled):
    youtube, req, _, api, history = scheduled
    youtube.upload(req, lambda _: None, CancelToken())
    api.videos.return_value.list.return_value.execute.return_value = {'items': [{
        'id': VIDEO, 'snippet': {'channelId': CHANNEL}, 'status': {'privacyStatus': 'private'}}]}
    assert youtube.sync_scheduled() == []
    job = history.list_scheduled()[0]
    assert job['schedule_needs_review'] is False and job['uploaded_at'] is None


def test_sync_batches_fifty_and_uses_each_accounts_token(scheduled, monkeypatch):
    from app.services.youtube import service
    from tests.services.test_youtube_accounts import credentials
    youtube, req, _, api_a, history = scheduled
    b = 'UC' + 'b' * 22
    creds = credentials(b)
    youtube._secrets.set(service.auth.account_token_key(b), creds.to_json())
    rows = youtube._settings.get('youtube_accounts')
    youtube._settings.set('youtube_accounts', rows + [{'id': b, 'title': 'B', 'thumbnail_url': None, 'is_default': False}])
    session_b = service._YouTubeSession(secret_store=service.AccountTokenStore(youtube._secrets, b))
    session_b._credentials = creds
    session_b._api = Mock()
    youtube._sessions[b] = session_b
    ids_a = [f'a{i:010d}' for i in range(51)]
    for channel, ids in ((CHANNEL, ids_a), (b, ['b0000000000'])):
        for video_id in ids:
            history.add({'status': JobStatus.SCHEDULED, 'scheduled_at': req.publish_at,
                'youtube_video_id': video_id, 'channel_id': channel, 'youtube_channel_id': channel})
    def public_items(channel, **kwargs):
        return Mock(execute=Mock(return_value={'items': [{'id': value, 'snippet': {'channelId': channel},
            'status': {'privacyStatus': 'public'}} for value in kwargs['id'].split(',')]}))
    api_a.videos.return_value.list.side_effect = lambda **kw: public_items(CHANNEL, **kw)
    session_b._api.videos.return_value.list.side_effect = lambda **kw: public_items(b, **kw)
    result = youtube.sync_scheduled()
    assert len(result) == 52 and not history.list_scheduled()
    assert [len(call.kwargs['id'].split(',')) for call in api_a.videos.return_value.list.call_args_list] == [50, 1]
    assert session_b._api.videos.return_value.list.call_count == 1


def test_scheduled_upload_updates_existing_local_job_without_losing_tiktok_identity(scheduled):
    youtube, req, _, _, history = scheduled
    job_id = history.add({'video_id': '1234567890', 'local_mp4_path': str(req.path), 'title': 'Original'})
    youtube.upload(req, lambda _: None, CancelToken())
    assert history.list_scheduled()[0]['id'] == job_id
    assert history.get(job_id)['tiktok_video_id'] == '1234567890'
