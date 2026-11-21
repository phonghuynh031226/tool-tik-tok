"""Service Container for dependency injection into UI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from PySide6.QtCore import QObject, Signal, Slot, QThreadPool
from PySide6.QtWidgets import QLabel
from typing import Optional, ClassVar

from app.ui import i18n as _i18n
from app.contracts import (
    ContentGenerator, HistoryRepository, SecretStore, SettingsStore,
    TikTokService, YouTubeService, ChannelAccount, ChannelInfo,
)
from app.services.tiktok.service import TikTokService as RealTikTokService
from app.services.youtube.service import YouTubeService as RealYouTubeService
from app.db.repository import SQLiteHistoryRepository
from app.security.secrets import KeyringSecretStore
from app.security.settings import JSONSettingsStore
from app.services.gemini import GeminiContentGenerator


class GeminiSelection(QObject):
    changed = Signal(str, str)


class _ConnectionAttempt(QObject):
    def __init__(self, connection, generation):
        super().__init__(connection)
        self.connection, self.generation = connection, generation

    @Slot(object)
    def finished(self, channel):
        if self.generation == self.connection._generation:
            self.connection.busy = False
            self.connection.set_channel(channel)

    @Slot(str)
    def failed(self, message):
        if self.generation == self.connection._generation:
            self.connection.busy = False
            self.connection.set_channel(None)
            self.connection.error.emit(message)

    @Slot(object)
    def accounts(self, accounts):
        if self.generation == self.connection._generation:
            self.connection.set_accounts(accounts)


class YouTubeConnection(QObject):
    changed = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.channel = None
        self.accounts = []
        self.accounts_loaded = False
        self.selected_channel_id = None
        self.busy = False
        self._generation = 0
        self._worker = None
        self._upload_owner = None
        self._restore_started = False

    def begin_upload(self, owner):
        if self.busy:
            return False
        self._upload_owner = owner
        self.busy = True
        self.changed.emit()
        return True

    def end_upload(self, owner):
        if self._upload_owner is owner:
            self._upload_owner = None
            self.busy = False
            self.changed.emit()

    def set_channel(self, channel):
        self.channel = channel
        if channel is not None:
            self.selected_channel_id = channel.id
        if channel is not None and not any(a.id == channel.id for a in self.accounts):
            self.accounts.append(ChannelAccount(channel.id, channel.title, status='connected'))
        self.changed.emit()

    def set_accounts(self, accounts):
        self.accounts = [a for a in accounts if isinstance(a, ChannelAccount)]
        self.accounts_loaded = True
        selected = next((a for a in self.accounts if a.id == self.selected_channel_id), None)
        if selected is None:
            selected = next((a for a in self.accounts if a.is_default), None)
        self.channel = (ChannelInfo(selected.id, selected.title)
                        if selected is not None and selected.status == 'connected' else None)
        if self.busy and self._upload_owner is None:
            self.channel = None  # Restoration publishes verification atomically on finished.
        self.selected_channel_id = selected.id if selected else None
        self.changed.emit()

    def select_channel(self, channel_id):
        self.selected_channel_id = channel_id
        account = next((a for a in self.accounts if a.id == channel_id), None)
        self.channel = (ChannelInfo(account.id, account.title)
                        if account is not None and account.status == 'connected' else None)
        self.changed.emit()

    def clear(self):
        if getattr(self, '_worker', None) and hasattr(self._worker, 'cancel'):
            try:
                self._worker.cancel()
            except Exception:
                pass
        self._generation += 1
        self.channel = None
        self.accounts = []
        self.accounts_loaded = False
        self.selected_channel_id = None
        self.busy = False
        self.changed.emit()

    def cancel_pending(self):
        """Invalidate queued restore callbacks before the owning window closes."""
        self._generation += 1
        worker, self._worker = self._worker, None
        if worker is not None:
            cancel = getattr(worker, 'cancel', None)
            if callable(cancel):
                cancel()
        self.busy = False
        self._upload_owner = None

    def restore_service(self, service):
        if self._restore_started or self.busy or self.channel is not None or not callable(getattr(service, 'restore_session', None)):
            return
        self._restore_started = True
        self.connect_service(service, restore=True)

    def connect_service(self, service, *, restore=False):
        from app.workers.service_workers import YouTubeConnectWorker, YouTubeRestoreWorker
        if self.busy:
            return
        if not restore:
            from app.workers.youtube_restore import invalidate_accounts
            invalidate_accounts(service)
        self.clear()
        self.busy = True
        self.changed.emit()
        generation = self._generation
        worker = YouTubeRestoreWorker(service) if restore else YouTubeConnectWorker(service)
        self._worker = worker
        self._attempt = _ConnectionAttempt(self, generation)
        worker.signals.finished.connect(self._attempt.finished)
        worker.signals.error.connect(self._attempt.failed)
        worker.signals.accounts_loaded.connect(self._attempt.accounts)
        QThreadPool.globalInstance().start(worker)


@dataclass
class ServiceContainer:
    """Holds references to all application services.

    Allows plugging in either Fake services (dev/test) or Real services (production)
    without modifying any UI widgets or controllers.
    """

    automatic_background_tasks: ClassVar[bool] = True

    @property
    def run_automatic_background(self):
        return self.automatic_background_tasks or not self.is_fake

    tiktok: TikTokService
    generator: ContentGenerator
    youtube: YouTubeService
    history: HistoryRepository
    secrets: SecretStore
    settings: SettingsStore
    connection: YouTubeConnection = field(default_factory=YouTubeConnection, init=False)
    gemini_selection: GeminiSelection = field(default_factory=GeminiSelection, init=False)

    @property
    def is_fake(self):
        return type(self.youtube).__module__ == 'app.services.fakes'

    def upload_enabled(self, dry_run=False):
        channel = self.connection.channel
        account = next((a for a in self.connection.accounts if channel is not None and a.id == channel.id), None)
        return not self.connection.busy and (dry_run or (not self.is_fake and channel is not None
            and (account is not None and account.status == 'connected')
            and re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel.id) is not None))

    def valid_upload_result(self, result):
        return (not self.is_fake and re.fullmatch(r'[A-Za-z0-9_-]{11}', str(getattr(result, 'video_id', ''))) is not None
                and re.fullmatch(r'UC[A-Za-z0-9_-]{22}', str(getattr(result, 'channel_id', ''))) is not None)

    def add_mode_banner(self, page):
        if self.is_fake:
            window = page.window()
            if hasattr(window, 'statusBar'):
                if window.property('studio_fake_banner'):
                    return
                window.setProperty('studio_fake_banner', True)
                banner = _i18n.ui(QLabel('CHẾ ĐỘ GIẢ LẬP — Không kết nối hay upload thật', window))
                window.statusBar().addPermanentWidget(banner, 1)
            else:
                banner = _i18n.ui(QLabel('CHẾ ĐỘ GIẢ LẬP — Không kết nối hay upload thật', page))
                page.layout().insertWidget(0, banner)
            banner.setObjectName('simulationBanner')
            banner.setStyleSheet('background:#854d0e;color:white;padding:8px;font-weight:bold;')

    @classmethod
    def create_default(cls) -> ServiceContainer:
        """Create production services sharing secure storage."""
        secrets = KeyringSecretStore()
        settings = JSONSettingsStore()
        generator = GeminiContentGenerator(
            secret_store=secrets,
            settings_store=settings,
        )
        history = SQLiteHistoryRepository(secret_store=secrets)
        return cls(
            tiktok=RealTikTokService(),
            generator=generator,
            youtube=RealYouTubeService(secret_store=secrets, settings_store=settings, history_repository=history),
            history=history,
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
        _default_container = (ServiceContainer.create_fake() if os.environ.get('STUDIO_USE_FAKES') == '1'
                              else ServiceContainer.create_default())
    return _default_container


def set_services(container: ServiceContainer) -> None:
    """Override the global service container with custom services."""
    global _default_container
    _default_container = container
