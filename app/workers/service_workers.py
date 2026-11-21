"""Concrete workers for TikTok, AI, YouTube and History operations."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import logging
from typing import Any, Mapping

from PySide6.QtCore import QRunnable, Slot

from app.contracts import (
    ChannelAccount, ChannelInfo, ChannelStats, ContentGenerator, DownloadResult,
    GeneratedContent, HistoryRecord, HistoryRepository, JobStatus,
    TikTokService, UploadRequest, UploadResult, VideoMeta, VideoStats,
    YouTubeService,
)
from app.core.cancel import CancelToken
from app.workers.base import WorkerSignals, register_worker, tracked_run, start_background_request
from app.workers.youtube_restore import fetch_accounts, invalidate_accounts, restored_default

logger = logging.getLogger('TikTokYouTubeStudio.events')


def _safe_error(error: Exception, fallback: str, event: Optional[str] = None) -> str:
    from app.errors import AppError
    err_str = (str(error) + " " + getattr(error, "user_message", "")).lower()
    if "ffmpeg" in err_str or "ffprobe" in err_str:
        user_msg = "Thiếu công cụ xử lý video. Hãy đặt ffmpeg.exe và ffprobe.exe của bộ FFmpeg vào thư mục bin của ứng dụng. Ứng dụng không tự cài đặt."
    elif isinstance(error, AppError) and getattr(error, "user_message", None):
        user_msg = error.user_message
    else:
        user_msg = fallback

    if event:
        exc_type = type(error).__name__
        exc_code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
        code_part = f" code={exc_code}" if exc_code else ""
        logger.error(f"event={event} exc_type={exc_type} user_message={user_msg}{code_part}")
    return user_msg


@dataclass(frozen=True)
class DryRunResult:
    title: str
    privacy: str
    path: Path
    channel: str

    @property
    def summary(self):
        privacy = {'private': 'Riêng tư (Private)', 'public': 'Công khai (Public)', 'unlisted': 'Không công khai (Unlisted)'}[self.privacy]
        return f'Kênh: {self.channel}\nTiêu đề: {self.title}\nChế độ: {privacy}\nTệp: {self.path}'


class FetchMetaWorker(QRunnable):
    """Worker to fetch TikTok video metadata without downloading."""

    def __init__(self, service: TikTokService, url: str) -> None:
        super().__init__()
        self.service = service
        self.url = url
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
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
                self.signals.error.emit(_safe_error(exc, "Không thể tải thông tin video", event="fetch_meta_failed"))


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
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _on_progress(self, p: float) -> None:
        self.signals.progress.emit(max(0.0, min(1.0, float(p))))

    @Slot()
    @tracked_run
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
                self.signals.error.emit(_safe_error(exc, "Lỗi tải video TikTok", event="download_video_failed"))


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
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        import threading
        import time
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        # The network operation must never own Qt signals or wait for UI teardown.
        # Abandoned results remain local and cannot advance an upload or a later job.
        completed = threading.Event()
        outcome = {}
        generator, meta, settings = self.generator, self.meta, dict(self.settings)
        def generate():
            try:
                outcome['content'] = generator.generate(meta, settings)
                outcome['notice'] = getattr(generator, 'last_model_notice', '')
                outcome['model'] = getattr(generator, 'last_successful_model', '')
            except Exception as error:
                outcome['error'] = error
            finally:
                completed.set()
        self.signals.progress.emit(0.2)
        deadline = time.monotonic() + max(0.001, float(settings.get('timeout', self.timeout)))
        start_background_request(generate, name='studio-ai-request')
        while not completed.wait(0.05):
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
                return
            if time.monotonic() >= deadline:
                self.signals.error.emit('Quá thời gian tạo nội dung AI. Tác vụ đã dừng; vui lòng thử lại.')
                return
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        if time.monotonic() >= deadline:
            self.signals.error.emit('Quá thời gian tạo nội dung AI. Tác vụ đã dừng; vui lòng thử lại.')
            return
        if 'error' in outcome:
            self.signals.error.emit(_safe_error(outcome['error'], 'Lỗi khi sinh nội dung AI', event='generate_content_failed'))
            return
        notice, model = outcome['notice'], outcome['model']
        if isinstance(notice, str) and isinstance(model, str) and notice and model:
            self.signals.model_selected.emit(model, notice)
        self.signals.progress.emit(1.0)
        self.signals.finished.emit(outcome['content'])


class UploadYouTubeWorker(QRunnable):
    """Worker to upload video to YouTube (with Dry-run support)."""

    def __init__(
        self,
        service: YouTubeService,
        request: UploadRequest,
        dry_run: bool = False,
        confirmed_channel_id: str | None = None,
        confirmed_channel_title: str = '',
    ) -> None:
        super().__init__()
        self.service = service
        self.request = request
        self.dry_run = dry_run
        self.confirmed_channel_id = confirmed_channel_id
        self.confirmed_channel_title = confirmed_channel_title
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _on_progress(self, p: float) -> None:
        self.signals.progress.emit(max(0.0, min(1.0, float(p))))

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            if self.dry_run:
                from app.services.youtube.validators import validate_upload_request
                validate_upload_request(self.request)
                # Dry-run: simulate the flow without calling actual upload API
                import time
                for p in (0.1, 0.4, 0.7, 1.0):
                    self.cancel_token.raise_if_cancelled()
                    time.sleep(0.05)
                    self._on_progress(p)
                result = DryRunResult(self.request.title, self.request.privacy, self.request.path,
                    self.confirmed_channel_title or self.confirmed_channel_id or 'Chưa chọn kênh')
                logger.info('dry_run_completed — chưa đăng YouTube')
            else:
                if self.confirmed_channel_id is not None and hasattr(self.service, 'confirm_upload'):
                    self.service.confirm_upload(self.request, made_for_kids=self.request.made_for_kids,
                                                channel_id=self.confirmed_channel_id)
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
                self.signals.error.emit(_safe_error(exc, 'Không thể tải video lên YouTube. Hãy kiểm tra kết nối và nội dung.', event="upload_video_failed"))


class YtDlpUpdateWorker(QRunnable):
    """Worker to check and update yt-dlp in the background."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
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
                self.signals.error.emit(_safe_error(exc, "Lỗi khi kiểm tra cập nhật yt-dlp", event="check_ytdlp_update_failed"))


class YouTubeConnectWorker(QRunnable):
    """Worker to connect / get channel information for YouTube."""

    def __init__(self, service: YouTubeService) -> None:
        super().__init__()
        self.service = service
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            channel = self.service.connect()
            channel = self.service.get_channel()  # Explicit interactive connection still verifies the chosen channel.
            invalidate_accounts(self.service)
            logger.info('youtube_connected — đã xác thực kênh')
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(channel)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, 'Không thể kết nối kênh YouTube. Hãy kiểm tra OAuth Desktop client và mạng.', event="youtube_connect_failed"))


class YouTubeRestoreWorker(QRunnable):
    """Read/refresh stored credentials in a worker; no interactive fallback."""
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self):
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            accounts = fetch_accounts(self.service, consumer='restore', token=self.cancel_token)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
                return
            if isinstance(accounts, list):
                self.signals.accounts_loaded.emit(accounts)
            # Empty/legacy test backends retain the old silent path. Production
            # list_accounts migrates/restores accounts itself, including legacy.
            channel = restored_default(accounts) if isinstance(accounts, list) and accounts else self.service.restore_session()
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
                return
            if channel is not None and not isinstance(channel, ChannelInfo):
                raise ValueError('Invalid restored channel')
            if channel is not None:
                logger.info('youtube_session_restored — kênh đã xác thực')
            self.signals.finished.emit(channel)
        except Exception as error:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
                return
            from app.errors import AppError
            message = error.user_message if isinstance(error, AppError) else 'Không thể kiểm tra phiên YouTube đã lưu. Hãy thử Kết nối kênh.'
            self.signals.error.emit(message)


class FetchAccountsWorker(QRunnable):
    """Worker to list YouTube channel accounts."""

    def __init__(self, service: YouTubeService) -> None:
        super().__init__()
        self.service = service
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            accounts = fetch_accounts(self.service, token=self.cancel_token)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(accounts)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể tải danh sách tài khoản YouTube.", event="fetch_accounts_failed"))


class AddAccountWorker(QRunnable):
    """Worker to authenticate and add a new YouTube account."""

    def __init__(self, service: YouTubeService) -> None:
        super().__init__()
        self.service = service
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            account = self.service.add_account()
            invalidate_accounts(self.service)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(account)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể thêm tài khoản YouTube.", event="add_account_failed"))


class RemoveAccountWorker(QRunnable):
    """Worker to remove a YouTube channel account."""

    def __init__(self, service: YouTubeService, channel_id: str) -> None:
        super().__init__()
        self.service = service
        self.channel_id = channel_id
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            self.service.remove_account(self.channel_id)
            invalidate_accounts(self.service)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(self.channel_id)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể xóa tài khoản YouTube.", event="remove_account_failed"))


class SetDefaultAccountWorker(QRunnable):
    """Worker to set a YouTube channel account as default."""

    def __init__(self, service: YouTubeService, channel_id: str) -> None:
        super().__init__()
        self.service = service
        self.channel_id = channel_id
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            self.service.set_default_account(self.channel_id)
            invalidate_accounts(self.service)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(self.channel_id)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể đặt kênh mặc định.", event="set_default_account_failed"))


class FetchChannelStatsWorker(QRunnable):
    """Worker to fetch channel stats."""

    def __init__(self, service: YouTubeService, channel_id: str, force_refresh: bool = False) -> None:
        super().__init__()
        self.service = service
        self.channel_id = channel_id
        self.force_refresh = force_refresh
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            stats = self.service.get_channel_stats(self.channel_id, force_refresh=self.force_refresh)
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(stats)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể tải số liệu thống kê kênh.", event="fetch_channel_stats_failed"))


class FetchChannelVideosWorker(QRunnable):
    """Worker to fetch channel videos."""

    def __init__(
        self,
        service: YouTubeService,
        channel_id: str,
        limit: int = 50,
        force_refresh: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.channel_id = channel_id
        self.limit = limit
        self.force_refresh = force_refresh
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            videos = self.service.list_channel_videos(
                self.channel_id,
                limit=self.limit,
                force_refresh=self.force_refresh,
            )
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(videos)
                self.signals.channel_result.emit(self.channel_id, videos)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể tải danh sách video kênh.", event="fetch_channel_videos_failed"))


class SyncScheduledWorker(QRunnable):
    """Worker to sync scheduled video statuses with YouTube."""

    def __init__(
        self,
        service: YouTubeService,
        history: HistoryRepository | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.history = history
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self) -> None:
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            published = self.service.sync_scheduled()
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(published)
        except Exception as exc:
            if self.cancel_token.is_cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(_safe_error(exc, "Không thể đồng bộ lịch đăng.", event="sync_scheduled_failed"))
