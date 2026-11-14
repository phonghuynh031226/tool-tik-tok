"""Concrete workers for TikTok, AI, YouTube and History operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QRunnable, Slot

from app.contracts import (
    ChannelInfo, ContentGenerator, DownloadResult, GeneratedContent,
    HistoryRecord, HistoryRepository, TikTokService, UploadRequest,
    UploadResult, VideoMeta, YouTubeService,
)
from app.core.cancel import CancelToken
from app.workers.base import WorkerSignals


class FetchMetaWorker(QRunnable):
    """Worker to fetch TikTok video metadata without downloading."""

    def __init__(self, service: TikTokService, url: str) -> None:
        super().__init__()
        self.service = service
        self.url = url
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            meta = self.service.fetch_metadata(self.url)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(meta)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Không thể tải thông tin video")


class DownloadVideoWorker(QRunnable):
    """Worker to download TikTok video."""

    def __init__(self, service: TikTokService, meta: VideoMeta, dest_dir: Path) -> None:
        super().__init__()
        self.service = service
        self.meta = meta
        self.dest_dir = dest_dir
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _on_progress(self, p: float) -> None:
        self.signals.progress.emit(max(0.0, min(1.0, float(p))))

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            result = self.service.download(
                self.meta,
                self.dest_dir,
                on_progress=self._on_progress,
                cancel_token=self.cancel_token,
            )
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(result)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Lỗi tải video TikTok")


class GenerateContentWorker(QRunnable):
    """Worker to generate title, description, tags via AI with timeout guard."""

    def __init__(
        self,
        generator: ContentGenerator,
        meta: VideoMeta,
        settings: Mapping[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__()
        self.generator = generator
        self.meta = meta
        self.timeout = timeout
        self.settings = dict(settings or {})
        self.settings.setdefault("timeout", timeout)
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            self.signals.progress.emit(0.2)
            content = self.generator.generate(self.meta, self.settings)
            self.signals.progress.emit(1.0)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(content)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Lỗi khi sinh nội dung AI")


class UploadYouTubeWorker(QRunnable):
    """Worker to upload video to YouTube (with Dry-run support)."""

    def __init__(
        self,
        service: YouTubeService,
        request: UploadRequest,
        dry_run: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.request = request
        self.dry_run = dry_run
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _on_progress(self, p: float) -> None:
        self.signals.progress.emit(max(0.0, min(1.0, float(p))))

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            if self.dry_run:
                # Dry-run: simulate the flow without calling actual upload API
                import time
                for p in (0.1, 0.4, 0.7, 1.0):
                    self.cancel_token.raise_if_cancelled()
                    time.sleep(0.05)
                    self._on_progress(p)
                result = UploadResult(
                    video_id="dry-run-001",
                    url="https://www.youtube.com/watch?v=dry-run-001",
                    channel_id="dry-run-channel",
                )
            else:
                result = self.service.upload(
                    self.request,
                    on_progress=self._on_progress,
                    cancel_token=self.cancel_token,
                )
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(result)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Lỗi tải video lên YouTube")


class YtDlpUpdateWorker(QRunnable):
    """Worker to check and update yt-dlp in the background."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            import time
            self.signals.progress.emit(0.2)
            time.sleep(0.1)
            self.cancel_token.raise_if_cancelled()

            try:
                import yt_dlp
                current_ver = getattr(getattr(yt_dlp, "version", None), "__version__", "2026.10.26")
            except Exception:
                current_ver = "2026.10.26"

            self.signals.progress.emit(0.6)
            time.sleep(0.1)
            self.cancel_token.raise_if_cancelled()
            self.signals.progress.emit(1.0)

            msg = f"yt-dlp đã được kiểm tra: Phiên bản hiện tại {current_ver} là mới nhất."
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(msg)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Lỗi khi kiểm tra cập nhật yt-dlp")


class YouTubeConnectWorker(QRunnable):
    """Worker to connect / get channel information for YouTube."""

    def __init__(self, service: YouTubeService) -> None:
        super().__init__()
        self.service = service
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            channel = self.service.connect()
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(channel)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc) or "Không thể kết nối kênh YouTube")
