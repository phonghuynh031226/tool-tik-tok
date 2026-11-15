from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import Mock

import pytest

from app.contracts import ChannelStats, VideoStats, StatsCache
from app.db.stats_cache import SQLiteStatsCache
from app.errors import AuthExpired, ContentInvalid, QuotaExceeded, NetworkError
from app.services.youtube import auth, service
from tests.services.test_youtube_accounts import accounts, credentials, A
from tests.services.test_youtube_service import http_error


@pytest.fixture
def statistics(accounts):
    youtube, secrets, settings, authorized, clients, tmp_path = accounts
    authorized.append(credentials(A))
    youtube.add_account()
    cache = SQLiteStatsCache(tmp_path / 'stats.db')
    youtube._stats_cache = cache
    api = clients[A][0]
    api.channels.return_value.list.return_value.execute.return_value = {'items': [{
        'id': A, 'snippet': {'title': 'A'},
        'statistics': {'subscriberCount': '12300', 'viewCount': '999999', 'videoCount': '105'},
        'contentDetails': {'relatedPlaylists': {'uploads': 'UU-sample'}}}]}
    api.channels.reset_mock()
    return youtube, cache, api, secrets


def video(index, *, hidden=False):
    return {'id': f'v{index:010d}', 'snippet': {'channelId': A, 'title': f'Video {index}',
        'publishedAt': '2026-01-01T01:00:00Z', 'thumbnails': {'high': {'url': 'https://example.com/thumb.jpg'}}},
        'statistics': {'viewCount': str(index * 100), **({} if hidden else {'likeCount': '0', 'commentCount': '3'})},
        'status': {'privacyStatus': 'private', 'publishAt': '2099-01-01T00:00:00Z'},
        'contentDetails': {'duration': 'P1DT2H3M4.5S'}}


def test_channel_statistics_hidden_and_fresh_cache(statistics):
    youtube, cache, api, _ = statistics
    assert isinstance(cache, StatsCache)
    result = youtube.get_channel_stats(A)
    assert result.subscribers == 12300 and result.total_views == 999999 and result.video_count == 105
    assert result.fetched_at.tzinfo is not None
    api.channels.return_value.list.assert_called_once_with(part='snippet,statistics,contentDetails', mine=True)
    api.channels.reset_mock()
    assert youtube.get_channel_stats(A) == result
    api.channels.assert_not_called()
    api.channels.return_value.list.return_value.execute.return_value['items'][0]['statistics'] = {'hiddenSubscriberCount': True}
    hidden = youtube.get_channel_stats(A, force_refresh=True)
    assert hidden.subscribers_hidden and hidden.subscribers is None


def test_pagination_batches_order_and_optional_metrics(statistics, caplog):
    youtube, cache, api, _ = statistics
    pages = []
    for start, end, token in ((0, 50, 'page2'), (50, 100, 'page3'), (100, 105, None)):
        page = {'items': [{'contentDetails': {'videoId': f'v{i:010d}'}} for i in range(start, end)]}
        if token: page['nextPageToken'] = token
        pages.append(page)
    api.playlistItems.return_value.list.return_value.execute.side_effect = pages
    api.videos.return_value.list.side_effect = lambda **kw: Mock(execute=Mock(return_value={
        'items': [video(int(id[1:]), hidden=id.endswith('0')) for id in reversed(kw['id'].split(','))]}))
    with caplog.at_level(logging.INFO):
        result = youtube.list_channel_videos(A, limit=105)
    assert len(result) == 105 and result[0].video_id == 'v0000000000' and result[-1].views == 10400
    assert result[0].likes is None and result[0].comments is None
    assert result[1].likes == 0 and result[1].comments == 3
    assert result[0].duration_seconds == 93784.5 and result[0].privacy_status == 'private'
    assert result[0].scheduled_at.year == 2099 and result[0].published_at.tzinfo is not None
    assert [len(call.kwargs['id'].split(',')) for call in api.videos.return_value.list.call_args_list] == [50, 50, 5]
    assert api.playlistItems.return_value.list.call_args_list[1].kwargs['pageToken'] == 'page2'
    assert 'estimated_quota_units=7' in caplog.text
    assert cache.load_videos(A) == result
    api.reset_mock()
    assert youtube.list_channel_videos(A, limit=10) == result[:10]
    api.channels.assert_not_called()


@pytest.mark.parametrize('method', ['get_channel_stats', 'list_channel_videos'])
@pytest.mark.parametrize(('status', 'reason', 'error'), [(403, 'quotaExceeded', QuotaExceeded),
    (401, 'authError', AuthExpired), (400, 'badRequest', ContentInvalid), (429, 'rateLimitExceeded', NetworkError)])
def test_http_4xx_not_retried_without_cache(statistics, method, status, reason, error):
    youtube, _, api, _ = statistics
    execute = api.channels.return_value.list.return_value.execute
    execute.side_effect = http_error(status, reason)
    with pytest.raises(error): getattr(youtube, method)(A, force_refresh=True)
    assert execute.call_count == 1


@pytest.mark.parametrize('method', ['get_channel_stats', 'list_channel_videos'])
@pytest.mark.parametrize(('status', 'reason'), [(403, 'quotaExceeded'), (401, 'authError')])
def test_old_cache_on_failure_retains_fetched_at(statistics, caplog, method, status, reason):
    youtube, cache, api, _ = statistics
    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    if method == 'get_channel_stats':
        old = ChannelStats(channel_id=A, subscribers=10, fetched_at=stamp)
        cache.save_channel_stats(old)
    else:
        old = [VideoStats(video_id='v0000000001', title='Old', fetched_at=stamp)]
        cache.save_videos(A, old)
    api.channels.return_value.list.return_value.execute.side_effect = http_error(status, reason)
    with caplog.at_level(logging.WARNING):
        result = getattr(youtube, method)(A, force_refresh=True)
    assert result == old and 'cache' in caplog.text.lower()


def test_empty_video_cache_and_larger_limit_refresh(statistics):
    youtube, _, api, _ = statistics
    api.playlistItems.return_value.list.return_value.execute.return_value = {'items': []}
    assert youtube.list_channel_videos(A) == []
    api.reset_mock()
    assert youtube.list_channel_videos(A) == []
    api.channels.assert_not_called()


def test_sqlite_cache_roundtrip_isolation_replace_and_reopen(tmp_path):
    path = tmp_path / 'studio.db'
    cache = SQLiteStatsCache(path)
    stamp = datetime.now(timezone.utc)
    assert cache.load_channel_stats(A) is None and cache.load_videos(A) == []
    stats = ChannelStats(A, None, 100, 2, True, stamp)
    cache.save_channel_stats(stats)
    cache.save_videos(A, [VideoStats('id-b', 'Tiếng Việt', fetched_at=stamp), VideoStats('id-a', 'Second', fetched_at=stamp)])
    reopened = SQLiteStatsCache(path)
    assert reopened.load_channel_stats(A) == stats
    assert [v.video_id for v in reopened.load_videos(A)] == ['id-b', 'id-a']
    assert reopened.load_videos('other') == []
    reopened.save_videos(A, [])
    assert reopened.load_videos(A) == []


def test_larger_limit_refreshes_a_cached_prefix(statistics):
    youtube, cache, api, _ = statistics
    execute = api.playlistItems.return_value.list.return_value.execute
    execute.side_effect = [
        {'items': [{'contentDetails': {'videoId': f'v{i:010d}'}} for i in range(2)], 'nextPageToken': 'more'},
        {'items': [{'contentDetails': {'videoId': f'v{i:010d}'}} for i in range(3)]}]
    api.videos.return_value.list.side_effect = lambda **kw: Mock(execute=Mock(return_value={
        'items': [video(int(id[1:])) for id in kw['id'].split(',')]}))
    assert len(youtube.list_channel_videos(A, limit=2)) == 2
    assert not cache.load_video_window(A).complete
    assert len(youtube.list_channel_videos(A, limit=3)) == 3
    assert api.channels.return_value.list.call_count == 2


def test_cold_instance_uses_fresh_cache_without_building_api(statistics, monkeypatch):
    youtube, cache, api, secrets = statistics
    original = youtube.get_channel_stats(A)
    build = Mock(side_effect=AssertionError('Fresh cache must not build API or restore OAuth'))
    monkeypatch.setattr(service, 'build', build)
    reopened = service.YouTubeService(secret_store=secrets, settings_store=youtube._settings, stats_cache=cache)
    assert reopened.get_channel_stats(A) == original
    build.assert_not_called()


def test_expired_cached_statistics_refresh_automatically(statistics):
    youtube, cache, api, _ = statistics
    old = ChannelStats(channel_id=A, subscribers=1, fetched_at=datetime.now(timezone.utc) - timedelta(minutes=11))
    cache.save_channel_stats(old)
    assert youtube.get_channel_stats(A).subscribers == 12300
    api.channels.return_value.list.assert_called_once()


def test_local_expired_token_refreshes_once_and_saves_only_account_token(statistics, monkeypatch):
    youtube, _, _, secrets = statistics
    session = youtube._sessions[A]
    session._credentials.expiry = datetime(2020, 1, 1)
    def refresh(self, request):
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(type(session._credentials), 'refresh', refresh)
    assert youtube.get_channel_stats(A).subscribers == 12300
    assert secrets.get(auth.account_token_key(A))
    assert secrets.get(auth.TOKEN_KEY) is None


def test_refresh_rejected_is_auth_expired_without_api_retry(statistics, monkeypatch):
    from google.auth.exceptions import RefreshError
    youtube, _, api, secrets = statistics
    session = youtube._sessions[A]
    session._credentials.expiry = datetime(2020, 1, 1)
    def rejected(self, request):
        raise RefreshError('invalid_grant private diagnostic')
    monkeypatch.setattr(type(session._credentials), 'refresh', rejected)
    with pytest.raises(AuthExpired): youtube.get_channel_stats(A)
    api.channels.assert_not_called()
    assert secrets.get(auth.account_token_key(A)) is None


def test_5xx_retries_are_counted_in_quota_estimate(statistics, monkeypatch, caplog):
    youtube, _, api, _ = statistics
    execute = api.channels.return_value.list.return_value.execute
    payload = execute.return_value
    execute.side_effect = [http_error(503, 'backendError'), payload]
    monkeypatch.setattr(service, 'wait_backoff', Mock())
    with caplog.at_level(logging.INFO):
        assert youtube.get_channel_stats(A).subscribers == 12300
    assert execute.call_count == 2
    assert 'estimated_quota_units=2' in caplog.text


@pytest.mark.parametrize('limit', [-1, True, 1.5])
def test_invalid_limit_fails_before_api(statistics, limit):
    youtube, _, api, _ = statistics
    with pytest.raises(ValueError): youtube.list_channel_videos(A, limit=limit)
    api.channels.assert_not_called()


def test_zero_limit_returns_without_api(statistics):
    youtube, _, api, _ = statistics
    assert youtube.list_channel_videos(A, limit=0) == []
    api.channels.assert_not_called()
