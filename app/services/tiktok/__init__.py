"""TikTok backend; importing this package never downloads or updates anything."""

from .service import DownloadProgress, TikTokService

__all__ = ['DownloadProgress', 'TikTokService']
