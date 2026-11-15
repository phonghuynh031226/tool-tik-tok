"""TikTok Downloader dedicated page."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.contracts import DownloadResult, VideoMeta
from app.ui.components import AppButton, Card
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import DownloadVideoWorker, FetchMetaWorker


class TikTokPage(QWidget):
    """Dedicated TikTok download workspace."""

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
        self._active_download_worker: Optional[DownloadVideoWorker] = None

        self._init_ui()
        self._connect_state()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header
        header = QLabel("Tải Video TikTok Chất Lượng Cao", container)
        header.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        layout.addWidget(header)

        sub = QLabel(
            "Tự động tải video gốc không logo / watermark, bóc tách thông tin và chuẩn bị cho pipeline.",
            container,
        )
        sub.setProperty("class", "hintLabel")
        layout.addWidget(sub)

        # Main download Card
        card = Card(title="Nhập nguồn video", parent=container)
        c_layout = QVBoxLayout()
        c_layout.setSpacing(12)

        lbl_url = QLabel("Đường dẫn TikTok (URL):", card)
        lbl_url.setProperty("class", "fieldLabel")
        c_layout.addWidget(lbl_url)

        row = QHBoxLayout()
        self.edit_url = QLineEdit(card)
        self.edit_url.setPlaceholderText("https://www.tiktok.com/@.../video/...")
        self.edit_url.textChanged.connect(lambda t: setattr(self.state, "url", t.strip()))
        row.addWidget(self.edit_url, stretch=1)

        self.btn_paste = AppButton("Dán", variant="secondary", icon_name="content-paste", parent=card)
        self.btn_paste.clicked.connect(self._on_paste)
        row.addWidget(self.btn_paste)

        self.btn_download = AppButton("Bắt đầu tải", variant="primary", icon_name="download", parent=card)
        self.btn_download.clicked.connect(self._on_download)
        row.addWidget(self.btn_download)

        self.btn_pick_file = AppButton("Chọn MP4 từ máy", variant="secondary", icon_name="folder-open", parent=card)
        self.btn_pick_file.clicked.connect(self._on_pick_file)
        row.addWidget(self.btn_pick_file)
        c_layout.addLayout(row)

        # Progress
        self.progress_bar = QProgressBar(card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        c_layout.addWidget(self.progress_bar)

        card.add_layout(c_layout)
        layout.addWidget(card)

        # Details Card
        self.details_card = Card(title="Thông tin chi tiết video", parent=container)
        d_layout = QGridLayout()
        d_layout.setSpacing(10)

        self.lbl_title = QLabel("Tiêu đề: -")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet("font-weight: 600; color: #f8fafc;")
        d_layout.addWidget(self.lbl_title, 0, 0, 1, 2)

        self.lbl_author = QLabel("Kênh tác giả: -")
        self.lbl_author.setProperty("class", "hintLabel")
        d_layout.addWidget(self.lbl_author, 1, 0)

        self.lbl_duration = QLabel("Thời lượng: -")
        self.lbl_duration.setProperty("class", "hintLabel")
        d_layout.addWidget(self.lbl_duration, 1, 1)

        self.lbl_dimensions = QLabel("Kích thước: -")
        self.lbl_dimensions.setProperty("class", "hintLabel")
        d_layout.addWidget(self.lbl_dimensions, 2, 0)

        self.lbl_file_path = QLabel("Đường dẫn file lưu: -")
        self.lbl_file_path.setProperty("class", "hintLabel")
        d_layout.addWidget(self.lbl_file_path, 2, 1)

        self.details_card.add_layout(d_layout)
        layout.addWidget(self.details_card)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _connect_state(self) -> None:
        self.state.job_changed.connect(self._sync_state)

    def _sync_state(self) -> None:
        if self.edit_url.text() != self.state.url:
            self.edit_url.blockSignals(True)
            self.edit_url.setText(self.state.url)
            self.edit_url.blockSignals(False)

        if self.state.meta:
            self.lbl_title.setText(f"Tiêu đề: {self.state.meta.title}")
            self.lbl_author.setText(f"Kênh tác giả: {self.state.meta.author}")
            self.lbl_duration.setText(f"Thời lượng: {self.state.meta.duration or 'Không rõ'}s")
            self.lbl_dimensions.setText(
                f"Kích thước: {self.state.meta.width or 0} x {self.state.meta.height or 0}"
            )

        if self.state.local_video_path:
            self.lbl_file_path.setText(f"Đường dẫn file: {self.state.local_video_path}")

    @Slot()
    def _on_paste(self) -> None:
        clip = QGuiApplication.clipboard().text().strip()
        if clip:
            self.edit_url.setText(clip)
            self.state.url = clip

    @Slot()
    def _on_pick_file(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Chọn file MP4", "", "Video files (*.mp4 *.mkv *.mov);;All files (*.*)"
        )
        if fpath:
            self.state.set_local_file(Path(fpath))

    @Slot()
    def _on_download(self) -> None:
        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Chưa nhập liên kết", "Vui lòng nhập URL TikTok.")
            return

        self.btn_download.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)

        worker = FetchMetaWorker(self.services.tiktok, url)
        worker.signals.finished.connect(self._on_meta_fetched)
        worker.signals.error.connect(self._on_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_meta_fetched(self, meta: VideoMeta) -> None:
        self.state.meta = meta
        dest = Path(".tmp/downloads")
        dest.mkdir(parents=True, exist_ok=True)
        worker = DownloadVideoWorker(self.services.tiktok, meta, dest)
        self._active_download_worker = worker
        worker.signals.progress.connect(lambda p: self.progress_bar.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_downloaded)
        worker.signals.error.connect(self._on_error)
        self.thread_pool.start(worker)

    def _notify(self, toast_type: str, title: str, message: str = "") -> None:
        win = self.window()
        if win and hasattr(win, "notify"):
            win.notify(toast_type=toast_type, title=title, message=message)
        else:
            if toast_type in ("error", "critical"):
                QMessageBox.critical(self, title, message)
            elif toast_type == "warning":
                QMessageBox.warning(self, title, message)
            else:
                QMessageBox.information(self, title, message)

    @Slot(object)
    def _on_downloaded(self, res: DownloadResult) -> None:
        self.progress_bar.setValue(100)
        self.btn_download.setEnabled(True)
        self._active_download_worker = None
        self.state.set_download_result(res)
        self._notify("success", "Tải video hoàn tất", f"Đã lưu tệp video: {res.path.name}")

    @Slot(str)
    def _on_error(self, err: str) -> None:
        self.btn_download.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._active_download_worker = None
        self._notify("error", "Lỗi tải video", f"Thao tác thất bại: {err}")

