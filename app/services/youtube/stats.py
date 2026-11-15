"""Read-only statistics parsing and quota accounting.

YouTube may round subscriberCount (three significant figures); it is not an
exact subscriber count. Hidden subscribers and unavailable likes/comments are
None, never inferred as zero. Each list request attempt estimates one quota unit:
https://developers.google.com/youtube/v3/determine_quota_cost
"""
from datetime import datetime, timezone
import logging
import re

from app.contracts import ChannelStats, VideoStats
from app.errors import StatsUnavailable

_LOG = logging.getLogger(__name__)
_DURATION = re.compile(r'P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?')


def timestamp(value):
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise StatsUnavailable() from None


def duration(value):
    match = _DURATION.fullmatch(value) if isinstance(value, str) else None
    if not match or not any(match.groups()):
        raise StatsUnavailable()
    return sum(float(part or 0) * multiplier for part, multiplier in zip(match.groups(), (86400, 3600, 60, 1)))


def count(value, default=0):
    if value is None:
        return default
    try:
        if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
            raise ValueError()
        return int(value)
    except (ValueError, TypeError):
        raise StatsUnavailable() from None


def thumbnail(snippet):
    images = snippet.get('thumbnails', {})
    return next((images[key]['url'] for key in ('maxres', 'standard', 'high', 'medium', 'default')
                 if isinstance(images.get(key), dict) and isinstance(images[key].get('url'), str)), None)


class StatsReader:
    def __init__(self, session, policy, verify_identity):
        self.session, self.policy, self.verify_identity = session, policy, verify_identity
        self.quota_units = 0

    def request(self, factory):
        def execute():
            self.quota_units += 1
            return factory().execute(num_retries=0)
        payload = self.policy.call(execute)
        if not isinstance(payload, dict) or not isinstance(payload.get('items', []), list):
            raise StatsUnavailable()
        return payload

    def channel(self, channel_id):
        payload = self.request(lambda: self.session._api.channels().list(
            part='snippet,statistics,contentDetails', mine=True))
        items = payload.get('items', [])
        if len(items) != 1 or not isinstance(items[0], dict):
            raise StatsUnavailable()
        item = items[0]
        self.verify_identity(item)
        if item.get('id') != channel_id:
            raise StatsUnavailable()
        return item

    def channel_stats(self, channel_id):
        """Subscriber counts may be rounded by YouTube; hidden counts are None."""
        values = self.channel(channel_id).get('statistics', {})
        hidden = bool(values.get('hiddenSubscriberCount', False))
        return ChannelStats(channel_id=channel_id,
            subscribers=None if hidden else count(values.get('subscriberCount'), None),
            total_views=count(values.get('viewCount')), video_count=count(values.get('videoCount')),
            subscribers_hidden=hidden, fetched_at=datetime.now(timezone.utc))

    def videos(self, channel_id, limit):
        channel = self.channel(channel_id)
        playlist = channel.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
        if not isinstance(playlist, str) or not playlist:
            raise StatsUnavailable()
        ids, seen_ids, seen_tokens = [], set(), set()
        page_token = None
        while len(ids) < limit:
            params = dict(part='contentDetails', playlistId=playlist, maxResults=min(50, limit - len(ids)))
            if page_token:
                params['pageToken'] = page_token
            payload = self.request(lambda: self.session._api.playlistItems().list(**params))
            for item in payload.get('items', []):
                video_id = item.get('contentDetails', {}).get('videoId')
                if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    continue  # Deleted/unavailable playlist entries need not expose an id.
                if video_id not in seen_ids:
                    ids.append(video_id)
                    seen_ids.add(video_id)
                if len(ids) == limit:
                    break
            page_token = payload.get('nextPageToken')
            if not page_token:
                break
            if not isinstance(page_token, str) or page_token in seen_tokens:
                raise StatsUnavailable()
            seen_tokens.add(page_token)
        values = {}
        stamp = datetime.now(timezone.utc)
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            payload = self.request(lambda: self.session._api.videos().list(
                part='snippet,statistics,status,contentDetails', id=','.join(batch)))
            for item in payload.get('items', []):
                if item.get('id') not in batch:
                    raise StatsUnavailable()
                snippet, stats, status = item.get('snippet', {}), item.get('statistics', {}), item.get('status', {})
                if snippet.get('channelId', channel_id) != channel_id:
                    raise StatsUnavailable()
                values[item['id']] = VideoStats(video_id=item['id'], title=snippet.get('title', ''),
                    thumbnail_url=thumbnail(snippet), published_at=timestamp(snippet.get('publishedAt')),
                    scheduled_at=timestamp(status.get('publishAt')), privacy_status=status.get('privacyStatus', 'private'),
                    duration_seconds=duration(item.get('contentDetails', {}).get('duration')),
                    views=count(stats.get('viewCount')), likes=count(stats.get('likeCount'), None),
                    comments=count(stats.get('commentCount'), None), fetched_at=stamp)
        # API batch order is not guaranteed; preserve uploads-playlist order.
        return [values[video_id] for video_id in ids if video_id in values], not bool(page_token), stamp

    def log_quota(self):
        _LOG.info('YouTube statistics refresh: estimated_quota_units=%d', self.quota_units)
