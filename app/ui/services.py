"""Service Container for dependency injection into UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.contracts import (
    ContentGenerator, HistoryRepository, SecretStore, SettingsStore,
    TikTokService, YouTubeService,
)
from app.services.fakes import (
    FakeContentGenerator, FakeHistoryRepository, FakeSecretStore,
    FakeSettingsStore, FakeTikTokService, FakeYouTubeService,
)
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
        """Create container with real Gemini generator plugged in."""
        secrets = FakeSecretStore()
        settings = FakeSettingsStore()
        generator = GeminiContentGenerator(
            secret_store=secrets,
            settings_store=settings,
        )
        return cls(
            tiktok=FakeTikTokService(),
            generator=generator,
            youtube=FakeYouTubeService(),
            history=FakeHistoryRepository(),
            secrets=secrets,
            settings=settings,
        )

    @classmethod
    def create_fake(cls) -> ServiceContainer:
        """Create a container populated with deterministic in-memory fakes."""
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
    """Get the current global service container, defaulting to real Gemini generator."""
    global _default_container
    if _default_container is None:
        _default_container = ServiceContainer.create_default()
    return _default_container


def set_services(container: ServiceContainer) -> None:
    """Override the global service container with custom services."""
    global _default_container
    _default_container = container
