"""Isolate production-default account settings from the user's configuration."""
import pytest


@pytest.fixture(autouse=True)
def isolated_youtube_account_settings(monkeypatch, tmp_path):
    from app.security.settings import JSONSettingsStore
    from app.services.youtube import service
    monkeypatch.setattr(service, 'JSONSettingsStore',
                        lambda: JSONSettingsStore(tmp_path / 'youtube-settings.json'))
