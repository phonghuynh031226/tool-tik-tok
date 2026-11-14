"""Service Container for dependency injection into UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.contracts import (
    ContentGenerator, HistoryRepository, SecretStore, SettingsStore,
    TikTokService, YouTubeService,
)
from app.services.tiktok.service import TikTokService as RealTikTokService
from app.services.youtube.service import YouTubeService as RealYouTubeService
from app.db.repository import SQLiteHistoryRepository
from app.security.secrets import KeyringSecretStore
from app.security.settings import JSONSettingsStore
from app.services.gemini import GeminiContentGenerator


@dataclass
class ServiceContainer:
    """Holds references to all application services.

    Allows plugging in either Fake services (dev/test) or Real services (production)
    without modifying any UI widgets or controllers.
    """

    tiktok: TikTokService
    generator: ContentGenerator
    youtube: YouTubeService
    history: HistoryRepository
    secrets: SecretStore
    settings: SettingsStore

    @classmethod
    def create_default(cls) -> ServiceContainer:
        """Create production services sharing secure storage."""
        secrets = KeyringSecretStore()
        settings = JSONSettingsStore()
        generator = GeminiContentGenerator(
            secret_store=secrets,
            settings_store=settings,
        )
        return cls(
            tiktok=RealTikTokService(),
            generator=generator,
            youtube=RealYouTubeService(secret_store=secrets),
            history=SQLiteHistoryRepository(secret_store=secrets),
            secrets=secrets,
            settings=settings,
        )

    @classmethod
    def create_fake(cls) -> ServiceContainer:
        """Create a container populated with deterministic in-memory fakes."""
        from app.services.fakes import (
            FakeTikTokService, FakeContentGenerator, FakeYouTubeService,
            FakeHistoryRepository, FakeSecretStore, FakeSettingsStore,
        )
        return cls(
            tiktok=FakeTikTokService(),
            generator=FakeContentGenerator(),
            youtube=FakeYouTubeService(),
            history=FakeHistoryRepository(),
            secrets=FakeSecretStore(),
            settings=FakeSettingsStore(),
        )


_default_container: Optional[ServiceContainer] = None


def get_services() -> ServiceContainer:
    """Get the current global service container, defaulting to production services."""
    global _default_container
    if _default_container is None:
        _default_container = ServiceContainer.create_default()
    return _default_container


def set_services(container: ServiceContainer) -> None:
    """Override the global service container with custom services."""
    global _default_container
    _default_container = container
