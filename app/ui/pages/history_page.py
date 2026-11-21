"""History & Scheduling page: Past video records and Scheduled video tracker."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QDialog, QAbstractItemView,
)

from app.ui import i18n as _i18n
from app.contracts import HistoryRecord, JobStatus, UploadResult
from app.core.paths import resolve_download_directory
from app.ui import tokens
from app.ui.components import AppButton, Card, EmptyState, StatusBadge, ToastManager
from app.ui.icons import get_icon
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import SyncScheduledWorker


class VideoDetailsDialog(QDialog):
    def __init__(self, record, parent=None):
        super().__init__(parent)
        _i18n.title(self, 'Chi tiết video')
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        title = QLabel(str(record.get('youtube_title') or record.get('title') or 'Không tiêu đề'), self)
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet('font-size: 17px; font-weight: 600;')
        layout.addWidget(title)
        fields = [
            ('ID YouTube', record.get('youtube_video_id')),
            ('ID TikTok', record.get('tiktok_video_id') or record.get('video_id')),
            ('Đường dẫn file', record.get('local_mp4_path') or record.get('path') or record.get('local_video_path')),
            ('Chế độ hiển thị', record.get('privacy_status') or record.get('privacy')),
            ('Thông tin lỗi', record.get('error_message')),
        ]
        for name, value in fields:
            label = QLabel(f"{name}: {value or '—'}", self)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        close = _i18n.ui(AppButton('Đóng', variant='secondary', parent=self))
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


class HistoryPage(QWidget):
    """One video table with schedule countdowns and confirmed publication status."""

    navigate_requested = Signal(int)  # Emit target page index to MainWindow

    def __init__(
        self,
        job_state: JobState,
        services: ServiceContainer,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.state = job_state
        self.services = services
        self.thread_pool = QThreadPool.globalInstance()
        self._all_records: list[dict] = []
        self._current_records: list[dict] = []
        self._scheduled_records: list[dict] = []
        self._sync_worker: Optional[SyncScheduledWorker] = None
        self._sync_silent = False

        self._init_ui()
        self.refresh_history()

        # Timer to update countdown every 5 seconds
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdowns)
        if self.services.run_automatic_background:
            self._countdown_timer.start(5000)
        self._schedule_poll_timer = QTimer(self)
        self._schedule_poll_timer.setInterval(60000)
        self._schedule_poll_timer.timeout.connect(self._maybe_sync_scheduled)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()
        if self.services.run_automatic_background:
            self._schedule_poll_timer.start()
            QTimer.singleShot(0, self._maybe_sync_scheduled)

    def hideEvent(self, event):
        self._schedule_poll_timer.stop()
        super().hideEvent(event)

    @Slot()
    def _maybe_sync_scheduled(self):
        if (not self.isVisible() or self._sync_worker is not None
                or self.services.is_fake or self.services.connection.busy):
            return
        if not self.services.history.list_scheduled():
            return
        self._on_sync_scheduled_clicked(silent=True)

    def _notify(self, ntype: str, title: str, message: str) -> None:
        toast = ToastManager.instance()
        if toast:
            getattr(toast, ntype, toast.info)(title, message)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        info = QVBoxLayout()
        title = _i18n.ui(QLabel('Lịch sử & Lịch đăng', self))
        title.setStyleSheet('font-size: 22px; font-weight: 700;')
        info.addWidget(title)
        subtitle = _i18n.ui(QLabel('Theo dõi lịch sử video và thời gian phát hành.', self))
        subtitle.setProperty('class', 'hintLabel')
        info.addWidget(subtitle)
        header.addLayout(info, 1)

        self.count_label = QLabel(self)
        self.count_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 13px; font-weight: 500; margin-right: 8px;")
        header.addWidget(self.count_label)

        self.btn_export_csv = _i18n.ui(AppButton('Xuất CSV', variant='secondary', icon_name='export', parent=self))
        self.btn_export_csv.clicked.connect(self._export_csv)
        header.addWidget(self.btn_export_csv)
        layout.addLayout(header)

        # Retain search & filter objects hidden for backward compatibility & programmatic access
        self.input_search = QLineEdit(self)
        self.input_search.hide()
        self.input_search.textChanged.connect(self._on_search_changed)

        self.combo_status = QComboBox(self)
        for text, key in [('Tất cả', 'all'), ('Chờ công khai', 'waiting'),
                          ('Đã công khai', 'public'), ('Lỗi', 'failed')]:
            _i18n.add_item(self.combo_status, text, key)
        self.combo_status.currentIndexChanged.connect(self.refresh_history)
        header.insertWidget(1,self.combo_status)

        self.prog_sync = QProgressBar(self)
        self.prog_sync.setRange(0, 0)
        self.prog_sync.setFixedHeight(3)
        self.prog_sync.setTextVisible(False)
        self.prog_sync.hide()
        layout.addWidget(self.prog_sync)

        # Programmatic manual-sync hooks share the existing worker, no duplicate UI.
        self.btn_sync_scheduled = _i18n.ui(AppButton('Đồng bộ', parent=self))
        self.btn_refresh_scheduled = self.btn_sync_scheduled
        self.btn_sync_scheduled.clicked.connect(self._on_sync_scheduled_clicked)
        self.btn_sync_scheduled.hide()

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        _i18n.headers(self.table, ['Tiêu đề video', 'Kênh YouTube', 'Giờ công khai', 'Trạng thái', 'YouTube'])
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setMinimumSectionSize(120)
        for column, width in [(1, 150), (2, 185), (3, 145), (4, 140)]:
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f'''
            QTableWidget {{
                background-color: {tokens.BG_CARD};
                alternate-background-color: {tokens.BG_CARD_HOVER};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 12px;
                outline: none;
            }}
        ''')
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        layout.addWidget(self.table, 1)

        self.empty_history = EmptyState(
            icon_name='history',
            title='Không có video',
            description='Chưa có video nào trong lịch sử xuất bản.',
            parent=self
        )
        layout.addWidget(self.empty_history)

    @staticmethod
    def _status(record):
        status = record.get('processing_status') or record.get('status') or 'NEW'
        return status.value if hasattr(status, 'value') else str(status)

    @staticmethod
    def _publish_time(record):
        value = record.get('scheduled_at') or record.get('publish_at')
        try:
            value = datetime.fromisoformat(value) if isinstance(value, str) else value
            return value if isinstance(value, datetime) and value.utcoffset() is not None else None
        except ValueError:
            return None

    def _presentation(self, record):
        status = self._status(record)
        privacy = record.get('privacy_status') or record.get('privacy')
        due = self._publish_time(record)
        if status == 'DRY_RUN':
            return 'Chạy thử', 'info', 'all'
        if status == 'UPLOADED' and privacy == 'public' and (
                not due or record.get('schedule_public_confirmed') is True):
            return 'Đã công khai', 'success', 'public'
        if record.get('schedule_needs_review') or (due and (
                status == 'UPLOADED' or due <= datetime.now(timezone.utc))):
            return 'Cần kiểm tra', 'warning', 'failed'
        if status == 'SCHEDULED':
            return 'Chờ công khai', 'warning', 'waiting'
        if status in {'FAILED', 'CANCELLED'}:
            return ('Thất bại' if status == 'FAILED' else 'Đã hủy'), 'danger', 'failed'
        labels = {'NEW': 'Mới tạo', 'METADATA_OK': 'Đã lấy thông tin',
                  'DOWNLOADED': 'Đã tải về', 'CONTENT_READY': 'Nội dung sẵn sàng',
                  'UPLOADING': 'Đang tải lên', 'UPLOADED': 'Đã tải lên'}
        return labels.get(status, status), 'info', 'all'

    @Slot()
    def refresh_history(self) -> None:
        query = self.input_search.text().strip()
        try:
            records = (self.services.history.list(limit=1000,status=JobStatus.FAILED) if self.combo_status.currentData()=='failed' and not query else
                       self.services.history.search(query) if query else self.services.history.list())
        except Exception:
            records = []
        records = [dict(record) for record in records if not record.get('retry_resolved')]
        for record in records:
            if record.get('dry_run') is True or any(str(record.get(key) or '').startswith('dry-run')
                                                   for key in ('video_id', 'youtube_video_id')):
                record.update(status='DRY_RUN', processing_status='DRY_RUN', youtube_video_id=None,
                              youtube_url=None, url='')
        self._all_records = records
        self._scheduled_records = [r for r in records if self._status(r) == 'SCHEDULED']
        self._render_records(records)

    def _render_records(self, records):
        selected = self.combo_status.currentData() or 'all'
        visible = [r for r in records if selected == 'all' or self._presentation(r)[2] == selected]
        self._current_records = visible
        self.count_label.setText(f'{len(visible)} video')
        # Qt deletes replaced cell widgets later. Hide them now so a refresh or
        # resize cannot leave old badges/buttons painted over another column.
        for old_row in range(self.table.rowCount()):
            for column in (3, 4):
                previous = self.table.cellWidget(old_row, column)
                if previous is not None:
                    previous.hide()
        self.table.clearContents()
        self.table.setRowCount(len(visible))
        self.table.setVisible(bool(visible))
        self.empty_history.setVisible(not visible)
        accounts = {a.id: a.title for a in self.services.connection.accounts}
        current = self.services.connection.channel
        if current:
            accounts[current.id] = current.title
        for row, record in enumerate(visible):
            title = str(record.get('youtube_title') or record.get('title') or 'Không tiêu đề')
            channel = str(accounts.get(record.get('channel_id')) or record.get('channel_title') or '—')
            due = self._publish_time(record)
            when = due.astimezone().strftime('%d/%m/%Y %H:%M') if due else '—'
            status, kind, category = self._presentation(record)
            if due and self._status(record) == 'SCHEDULED':
                seconds = int((due - datetime.now(timezone.utc)).total_seconds())
                when += ('\nCòn %dh %02dm' % (seconds // 3600, seconds % 3600 // 60)
                         if seconds > 0 else '\nĐã đến giờ · Chờ xác nhận')
            for column, text in enumerate((title, channel, when, status)):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setToolTip(title)
                if column==3 and record.get('error_message'):
                    item.setToolTip(record['error_message'])
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, 3, StatusBadge(status=status, badge_type=kind))
            action = QWidget(self.table)
            bar = QHBoxLayout(action)
            bar.setContentsMargins(4, 6, 4, 6)
            bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            video_id = record.get('youtube_video_id')
            import re
            if self._status(record)=='FAILED' and record.get('url') and not video_id:
                button=_i18n.ui(AppButton('Chạy lại',variant='danger',icon_name='refresh',parent=action))
                button.setToolTip(record.get('error_message') or '')
                button.clicked.connect(lambda _checked=False,rec=dict(record): self._retry_failed(rec))
                bar.addWidget(button)
            elif self._status(record) != 'DRY_RUN' and re.fullmatch(r'[A-Za-z0-9_-]{11}', str(video_id or '')):
                url = 'https://www.youtube.com/watch?v=' + video_id
                button = _i18n.ui(AppButton('Mở', variant='secondary', icon_name='link', parent=action))
                button.setFixedHeight(32)
                button.clicked.connect(lambda _checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
                bar.addWidget(button)
            else:
                bar.addWidget(QLabel('—', action))
            self.table.setCellWidget(row, 4, action)

    @Slot(int, int)
    def _show_video_details(self, row, column):
        if column == 0 and 0 <= row < len(self._current_records):
            VideoDetailsDialog(self._current_records[row], self).exec()

    def _open_mp4_folder(self, path_str: str) -> None:
        p = Path(path_str) if path_str else None
        if p and p.exists():
            folder = p.parent if p.is_file() else p
        else:
            saved_dir = self.services.settings.get("download_dir") if self.services.settings else None
            folder = resolve_download_directory(saved_dir)
            folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _retry_failed(self, record):
        controller=getattr(self.window(),'automation',None)
        if controller is None:
            self._resume_job(record)
            return
        if controller.busy or controller.batch.active:
            self._notify('warning','Chưa chạy lại','Chờ hàng đợi hiện tại hoàn tất hoặc dừng hàng đợi trước.')
            return
        if not controller.armed_prompt_id:
            self._notify('warning','Chưa chạy lại','Bật prompt tự động hóa trước khi chạy lại link lỗi.')
            self.navigate_requested.emit(5)
            return
        if record.get('channel_id') and controller.channel_id!=record['channel_id']:
            self._notify('warning','Chưa chạy lại','Chọn đúng kênh của video lỗi trước khi chạy lại.')
            return
        from app.services.tiktok.url import validate_url
        try:
            url=validate_url(record['url'])
        except Exception:
            self._notify('error','Không thể chạy lại','Link nguồn không hợp lệ.')
            return
        page=controller.page
        page.batch_panel.mode.setCurrentIndex(0)
        page.input_url.setText(url)
        self.navigate_requested.emit(0)
        controller.consider_text(url)

    def _resume_job(self, rec: dict) -> None:
        self.state.load_from_record(rec)
        self.navigate_requested.emit(0)
        self._notify("info", "Tiếp tục tác vụ", f"Đã nạp tác vụ '{self.state.title or rec.get('video_id')}' vào Tổng quan.")

    def _export_csv(self) -> None:
        if not self._current_records:
            self._notify("warning", "Không có dữ liệu", "Không có bản ghi lịch sử nào để xuất CSV.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Xuất Lịch Sử Ra Tệp CSV", "history_export.csv", "CSV Files (*.csv);;Tất cả tập tin (*.*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Mã Video", "Tiêu đề", "URL", "Trạng thái",
                    "Chế độ hiển thị", "Đường dẫn file", "Hashtags", "Tags"
                ])
                for rec in self._current_records:
                    writer.writerow([
                        rec.get("id", ""),
                        rec.get("video_id", ""),
                        rec.get("title", ""),
                        rec.get("url", ""),
                        rec.get("status", ""),
                        rec.get("privacy", ""),
                        rec.get("path") or rec.get("local_video_path") or "",
                        " ".join(rec.get("hashtags", [])),
                        ", ".join(rec.get("tags", [])),
                    ])
            self._notify("success", "Xuất CSV thành công", f"Đã xuất {len(self._current_records)} bản ghi vào file.")
            QMessageBox.information(
                self,
                "Xuất CSV thành công",
                f"Đã xuất thành công {len(self._current_records)} bản ghi vào:\n{file_path}",
            )
        except Exception as exc:
            self._notify("error", "Lỗi xuất CSV", f"Không thể ghi file CSV: {exc}")
            QMessageBox.critical(self, "Lỗi xuất CSV", f"Không thể ghi file CSV: {exc}")

    @Slot(str)
    def _on_search_changed(self, text: str) -> None:
        self.refresh_history()

    # =========================================================================
    # SCHEDULED LOGIC
    # =========================================================================
    @Slot()
    def refresh_scheduled(self):
        self.refresh_history()

    @Slot()
    def _update_countdowns(self):
        if self.isVisible():
            self._render_records(self._all_records)

    @Slot()
    def _on_sync_scheduled_clicked(self, silent=False) -> None:
        if self._sync_worker is not None:
            return
        self._sync_silent = bool(silent)
        self.prog_sync.setVisible(True)
        self.btn_sync_scheduled.setEnabled(False)
        self.btn_refresh_scheduled.setEnabled(False)

        worker = SyncScheduledWorker(self.services.youtube, self.services.history)
        self._sync_worker = worker
        worker.signals.finished.connect(self._on_sync_finished)
        worker.signals.error.connect(self._on_sync_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_sync_finished(self, published: list[UploadResult]) -> None:
        self._sync_worker = None
        self.prog_sync.setVisible(False)
        self.btn_sync_scheduled.setEnabled(True)
        self.btn_refresh_scheduled.setEnabled(True)
        self.refresh_history()

        silent, self._sync_silent = self._sync_silent, False
        if silent:
            return
        count = len(published)
        if count > 0:
            self._notify("success", "Đồng bộ thành công", f"Đã có {count} video được YouTube chính thức công khai!")
        else:
            self._notify("info", "Đồng bộ hoàn tất", "Không có video nào chuyển trạng thái công khai.")

    @Slot(str)
    def _on_sync_error(self, err: str) -> None:
        self._sync_worker = None
        self.prog_sync.setVisible(False)
        self.btn_sync_scheduled.setEnabled(True)
        self.btn_refresh_scheduled.setEnabled(True)
        self.refresh_history()
        silent, self._sync_silent = self._sync_silent, False
        if not silent:
            self._notify("error", "Lỗi đồng bộ lịch đăng", err)


HistorySchedulePage = HistoryPage
