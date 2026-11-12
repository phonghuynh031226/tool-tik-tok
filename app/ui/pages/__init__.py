"""Pages package."""

from app.ui.pages.ai_page import AIPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.history_page import HistoryPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tiktok_page import TikTokPage
from app.ui.pages.youtube_page import YouTubePage

__all__ = [
    "DashboardPage",
    "TikTokPage",
    "AIPage",
    "YouTubePage",
    "HistoryPage",
    "SettingsPage",
]

