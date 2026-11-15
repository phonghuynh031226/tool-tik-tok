"""Pages package."""

from app.ui.pages.ai_page import AIPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.history_page import HistoryPage, HistorySchedulePage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tiktok_page import TikTokPage
from app.ui.pages.tools_page import ToolsPage
from app.ui.pages.youtube_channels_page import YouTubeChannelsPage
from app.ui.pages.youtube_page import YouTubePage

__all__ = [
    "DashboardPage",
    "TikTokPage",
    "AIPage",
    "ToolsPage",
    "YouTubePage",
    "YouTubeChannelsPage",
    "HistoryPage",
    "HistorySchedulePage",
    "SettingsPage",
]

