"""Tools page: Two standalone utility tabs for TikTok downloading and AI generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.contracts import DownloadResult, GeneratedContent, VideoMeta
from app.ui.model_loading import populate_models
from app.ui import tokens
from app.ui.components import AppButton, Card, EmptyState, ToastManager
from app.ui.icons import get_icon
from app.ui.services import ServiceContainer
from app.ui.state import JobState, format_hashtags
from app.workers import DownloadVideoWorker, FetchMetaWorker, GenerateContentWorker


class ToolsPage(QWidget):
    """Tools page containing standalone TikTok Downloader and AI Generator tabs."""

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
        self._active_ai_worker: Optional[GenerateContentWorker] = None
        self._downloaded_files: list[dict[str, str]] = []

        self._init_ui()
        self._connect_state()
        self.lbl_model_notice = QLabel(self)
        self.lbl_model_notice.setVisible(False)
        if hasattr(self.services, "gemini_selection"):
            self.services.gemini_selection.changed.connect(self._on_model_selected)

    @Slot(str, str)
    def _on_model_selected(self, model: str, notice: str) -> None:
        self.lbl_model_notice.setText(notice)
        idx = self.combo_model.findData(model)
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
        else:
            self.combo_model.addItem(model, model)
            self.combo_model.setCurrentIndex(self.combo_model.count() - 1)

    def _notify(self, ntype: str, title: str, message: str) -> None:
        toast = ToastManager.instance()
        if toast:
            getattr(toast, ntype, toast.info)(title, message)

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(12)

        # Tab Widget
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_MD}px; background-color: {tokens.BG_APP}; }}"
            f"QTabBar::tab {{ background-color: {tokens.BG_CARD}; color: {tokens.TEXT_SECONDARY}; "
            f"padding: 10px 20px; font-weight: 600; font-size: 13px; "
            f"border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }}"
            f"QTabBar::tab:selected {{ background-color: {tokens.BG_CARD_HOVER}; "
            f"color: {tokens.COLOR_PRIMARY}; border-bottom: 2px solid {tokens.COLOR_PRIMARY}; }}"
            f"QTabBar::tab:hover {{ background-color: {tokens.BG_CARD_HOVER}; color: {tokens.TEXT_PRIMARY}; }}"
        )

        # Tab 1: TikTok Downloader
        self.tab_tiktok = self._create_tiktok_tab()
        self.tab_widget.addTab(self.tab_tiktok, get_icon("download"), "Tải video TikTok")

        # Tab 2: AI Content Generator
        self.tab_ai = self._create_ai_tab()
        self.tab_widget.addTab(self.tab_ai, get_icon("sparkle"), "Nội dung AI")

        outer_layout.addWidget(self.tab_widget)

    # =========================================================================
    # TAB 1: TIKTOK DOWNLOADER
    # =========================================================================
    def _create_tiktok_tab(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        lbl_head = QLabel("Công cụ Tải Video TikTok Trực tiếp", container)
        lbl_head.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        layout.addWidget(lbl_head)

        lbl_sub = QLabel(
            "Tải video TikTok về máy không dính watermark, lưu vào thư mục tùy chọn mà không bắt buộc tạo tác vụ đầy đủ.",
            container,
        )
        lbl_sub.setProperty("class", "hintLabel")
        layout.addWidget(lbl_sub)

        # Input Card
        input_card = Card(title="Tải video mới", parent=container)
        c_layout = QVBoxLayout()
        c_layout.setSpacing(12)

        # URL row
        row_url = QHBoxLayout()
        row_url.setSpacing(8)
        self.input_url = QLineEdit(input_card)
        self.edit_url = self.input_url  # alias
        self.input_url.setPlaceholderText("Dán liên kết TikTok tại đây: https://www.tiktok.com/@.../video/...")
        row_url.addWidget(self.input_url, stretch=1)

        self.btn_paste = AppButton("Dán", variant="secondary", icon_name="paste", parent=input_card)
        self.btn_paste.clicked.connect(self._on_paste_tiktok)
        row_url.addWidget(self.btn_paste)

        self.btn_download = AppButton("Tải về máy", variant="primary", icon_name="download", parent=input_card)
        self.btn_download.clicked.connect(self._on_download_tiktok)
        row_url.addWidget(self.btn_download)

        self.btn_pick_file = AppButton("Chọn MP4 từ máy", variant="secondary", icon_name="folder", parent=input_card)
        self.btn_pick_file.clicked.connect(self._on_pick_file)
        row_url.addWidget(self.btn_pick_file)
        c_layout.addLayout(row_url)

        # Folder selection row
        row_folder = QHBoxLayout()
        row_folder.setSpacing(8)
        lbl_dir = QLabel("Thư mục lưu:", input_card)
        lbl_dir.setProperty("class", "fieldLabel")
        row_folder.addWidget(lbl_dir)

        default_dir = (
            self.services.settings.get("download_dir", ".tmp/downloads")
            if self.services.settings else ".tmp/downloads"
        )
        self.edit_download_dir = QLineEdit(input_card)
        self.edit_download_dir.setText(str(Path(default_dir).resolve()))
        row_folder.addWidget(self.edit_download_dir, stretch=1)

        self.btn_browse_folder = AppButton("Chọn thư mục...", variant="secondary", icon_name="browse", parent=input_card)
        self.btn_browse_folder.clicked.connect(self._on_browse_download_dir)
        row_folder.addWidget(self.btn_browse_folder)

        self.btn_open_folder = AppButton("Mở thư mục", variant="ghost", icon_name="link", parent=input_card)
        self.btn_open_folder.clicked.connect(self._on_open_download_folder)
        row_folder.addWidget(self.btn_open_folder)
        c_layout.addLayout(row_folder)

        # Progress bar
        row_prog = QHBoxLayout()
        self.progress_download = QProgressBar(input_card)
        self.progress_bar = self.progress_download  # alias
        self.progress_download.setRange(0, 100)
        self.progress_download.setValue(0)
        self.progress_download.setVisible(False)
        row_prog.addWidget(self.progress_download, stretch=1)

        self.btn_cancel_download = AppButton("Hủy", variant="danger", icon_name="cancel", parent=input_card)
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download)
        row_prog.addWidget(self.btn_cancel_download)
        c_layout.addLayout(row_prog)

        input_card.add_layout(c_layout)
        layout.addWidget(input_card)

        # Downloaded Videos Table Card
        table_card = Card(title="Danh sách video đã tải trong phiên", parent=container)
        t_layout = QVBoxLayout()
        t_layout.setSpacing(10)

        self.tbl_downloads = QTableWidget(table_card)
        self.tbl_downloads.setColumnCount(5)
        self.tbl_downloads.setHorizontalHeaderLabels([
            "Mã Video", "Tiêu đề", "Thời lượng", "Dung lượng", "Đường dẫn file"
        ])
        self.tbl_downloads.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_downloads.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_downloads.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_downloads.setAlternatingRowColors(True)
        self.tbl_downloads.setMinimumHeight(240)
        t_layout.addWidget(self.tbl_downloads)

        # Bottom toolbar for downloads table
        btn_bar = QHBoxLayout()
        self.btn_load_to_job = AppButton("Nạp vào Tổng quan", variant="primary", icon_name="upload", parent=table_card)
        self.btn_load_to_job.clicked.connect(self._on_load_selected_to_job)
        btn_bar.addWidget(self.btn_load_to_job)

        self.btn_open_selected_video = AppButton("Xem video", variant="secondary", icon_name="play", parent=table_card)
        self.btn_open_selected_video.clicked.connect(self._on_open_selected_video)
        btn_bar.addWidget(self.btn_open_selected_video)

        btn_bar.addStretch()
        t_layout.addLayout(btn_bar)

        table_card.add_layout(t_layout)
        layout.addWidget(table_card)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # =========================================================================
    # TAB 2: AI CONTENT GENERATOR
    # =========================================================================
    def _create_ai_tab(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        lbl_head = QLabel("Tạo Nội Dung Bằng AI (Gemini)", container)
        lbl_head.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        layout.addWidget(lbl_head)

        lbl_sub = QLabel(
            "Tự do tối ưu tiêu đề, mô tả chuẩn SEO, hashtags và từ khóa mà không bắt buộc có video hay kênh YouTube.",
            container,
        )
        lbl_sub.setProperty("class", "hintLabel")
        layout.addWidget(lbl_sub)

        # Input Card
        in_card = Card(title="Nguồn nội dung gốc", parent=container)
        in_layout = QVBoxLayout()
        in_layout.setSpacing(10)

        # Pull from current job button
        row_top = QHBoxLayout()
        self.btn_pull_current = AppButton("Lấy từ tác vụ hiện tại", variant="ghost", icon_name="restore", parent=in_card)
        self.btn_pull_current.clicked.connect(self._on_pull_from_current_job)
        row_top.addWidget(self.btn_pull_current)
        row_top.addStretch()
        in_layout.addLayout(row_top)

        lbl_orig_title = QLabel("Tiêu đề TikTok gốc:", in_card)
        lbl_orig_title.setProperty("class", "fieldLabel")
        in_layout.addWidget(lbl_orig_title)

        self.edit_ai_orig_title = QLineEdit(in_card)
        self.edit_ai_orig_title.setPlaceholderText("Nhập hoặc dán tiêu đề video gốc...")
        in_layout.addWidget(self.edit_ai_orig_title)

        lbl_orig_desc = QLabel("Mô tả TikTok gốc:", in_card)
        lbl_orig_desc.setProperty("class", "fieldLabel")
        in_layout.addWidget(lbl_orig_desc)

        self.edit_ai_orig_desc = QTextEdit(in_card)
        self.edit_ai_orig_desc.setPlaceholderText("Nhập mô tả, nội dung hoặc ghi chú về video...")
        self.edit_ai_orig_desc.setMaximumHeight(80)
        in_layout.addWidget(self.edit_ai_orig_desc)

        # Model & Tone row
        row_cfg = QHBoxLayout()
        row_cfg.setSpacing(12)

        lbl_model = QLabel("Mô hình AI:", in_card)
        lbl_model.setProperty("class", "fieldLabel")
        row_cfg.addWidget(lbl_model)

        self.combo_model = QComboBox(in_card)
        populate_models(self.combo_model, self.services, notify=False)
        row_cfg.addWidget(self.combo_model, stretch=1)

        lbl_tone = QLabel("Phong cách:", in_card)
        lbl_tone.setProperty("class", "fieldLabel")
        row_cfg.addWidget(lbl_tone)

        self.combo_tone = QComboBox(in_card)
        self.combo_tone.addItem("Hấp dẫn & Cuốn hút", "engaging")
        self.combo_tone.addItem("Hài hước & Thân thiện", "humorous")
        self.combo_tone.addItem("Chuyên nghiệp & Tin tức", "professional")
        self.combo_tone.addItem("Ngắn gọn & Súc tích", "concise")
        row_cfg.addWidget(self.combo_tone, stretch=1)

        self.btn_generate_ai = AppButton("Tạo nội dung AI", variant="primary", icon_name="sparkle", parent=in_card)
        self.btn_generate_ai.clicked.connect(self._on_generate_ai_clicked)
        row_cfg.addWidget(self.btn_generate_ai)

        in_layout.addLayout(row_cfg)

        self.progress_ai = QProgressBar(in_card)
        self.progress_ai.setRange(0, 100)
        self.progress_ai.setValue(0)
        self.progress_ai.setVisible(False)
        in_layout.addWidget(self.progress_ai)

        in_card.add_layout(in_layout)
        layout.addWidget(in_card)

        # Output Card
        out_card = Card(title="Nội dung đã tối ưu", parent=container)
        o_layout = QVBoxLayout()
        o_layout.setSpacing(12)

        # Title row
        title_head = QHBoxLayout()
        lbl_res_title = QLabel("Tiêu đề YouTube (tối đa 100 ký tự):", out_card)
        lbl_res_title.setProperty("class", "fieldLabel")
        title_head.addWidget(lbl_res_title)
        title_head.addStretch()

        self.lbl_title_counter = QLabel("0/100 ký tự", out_card)
        self.lbl_title_counter.setProperty("class", "charCounter")
        title_head.addWidget(self.lbl_title_counter)

        self.btn_copy_title = AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card)
        self.btn_copy_title.clicked.connect(lambda: self._copy_to_clip(self.edit_title.text(), "tiêu đề"))
        title_head.addWidget(self.btn_copy_title)
        o_layout.addLayout(title_head)

        self.edit_title = QLineEdit(out_card)
        self.edit_title.setPlaceholderText("Tiêu đề sinh bởi AI sẽ xuất hiện tại đây...")
        self.edit_title.textChanged.connect(self._update_title_counter)
        o_layout.addWidget(self.edit_title)

        # Description row
        desc_head = QHBoxLayout()
        lbl_res_desc = QLabel("Mô tả Video:", out_card)
        lbl_res_desc.setProperty("class", "fieldLabel")
        desc_head.addWidget(lbl_res_desc)
        desc_head.addStretch()

        self.btn_copy_desc = AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card)
        self.btn_copy_desc.clicked.connect(lambda: self._copy_to_clip(self.edit_desc.toPlainText(), "mô tả"))
        desc_head.addWidget(self.btn_copy_desc)
        o_layout.addLayout(desc_head)

        self.edit_desc = QTextEdit(out_card)
        self.edit_desc.setPlaceholderText("Mô tả sinh bởi AI sẽ xuất hiện tại đây...")
        self.edit_desc.setMinimumHeight(120)
        o_layout.addWidget(self.edit_desc)

        # Hashtags row
        hash_head = QHBoxLayout()
        lbl_res_hash = QLabel("Hashtags:", out_card)
        lbl_res_hash.setProperty("class", "fieldLabel")
        hash_head.addWidget(lbl_res_hash)
        hash_head.addStretch()

        self.btn_copy_hash = AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card)
        self.btn_copy_hash.clicked.connect(lambda: self._copy_to_clip(self.edit_hashtags.text(), "hashtags"))
        hash_head.addWidget(self.btn_copy_hash)
        o_layout.addLayout(hash_head)

        self.edit_hashtags = QLineEdit(out_card)
        self.edit_hashtags.setPlaceholderText("#trend #viral...")
        o_layout.addWidget(self.edit_hashtags)

        # Tags row
        tag_head = QHBoxLayout()
        lbl_res_tags = QLabel("Từ khóa tìm kiếm (Tags):", out_card)
        lbl_res_tags.setProperty("class", "fieldLabel")
        tag_head.addWidget(lbl_res_tags)
        tag_head.addStretch()

        self.btn_copy_tags = AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card)
        self.btn_copy_tags.clicked.connect(lambda: self._copy_to_clip(self.edit_tags.text(), "tags"))
        tag_head.addWidget(self.btn_copy_tags)
        o_layout.addLayout(tag_head)

        self.edit_tags = QLineEdit(out_card)
        self.edit_tags.setPlaceholderText("keyword1, keyword2, keyword3...")
        o_layout.addWidget(self.edit_tags)

        # Output Action Bar
        act_bar = QHBoxLayout()
        self.btn_copy_all = AppButton("Sao chép tất cả", variant="secondary", icon_name="copy", parent=out_card)
        self.btn_copy_all.clicked.connect(self._on_copy_all_ai)
        act_bar.addWidget(self.btn_copy_all)

        self.btn_apply_to_job = AppButton("Áp dụng vào Tổng quan", variant="primary", icon_name="check", parent=out_card)
        self.btn_apply_to_job.clicked.connect(self._on_apply_ai_to_job)
        act_bar.addWidget(self.btn_apply_to_job)

        act_bar.addStretch()
        o_layout.addLayout(act_bar)

        out_card.add_layout(o_layout)
        layout.addWidget(out_card)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # =========================================================================
    # LOGIC & SLOTS: TIKTOK
    # =========================================================================
    def _connect_state(self) -> None:
        if self.state:
            self.state.job_changed.connect(self._on_state_changed)
            self.state.content_changed.connect(self._on_content_changed)

    def _on_state_changed(self) -> None:
        if self.state.url and not self.input_url.text():
            self.input_url.setText(self.state.url)
        if self.state.hashtags:
            self.edit_hashtags.setText(format_hashtags(self.state.hashtags))
        if self.state.title and not self.edit_title.text():
            self.edit_title.setText(self.state.title)
        if self.state.description and not self.edit_desc.toPlainText():
            self.edit_desc.setPlainText(self.state.description)
        if self.state.tags and not self.edit_tags.text():
            self.edit_tags.setText(", ".join(self.state.tags))

    def _on_content_changed(self, content: GeneratedContent) -> None:
        if content:
            if content.title:
                self.edit_title.setText(content.title)
            if content.description:
                self.edit_desc.setPlainText(content.description)
            if content.hashtags:
                self.edit_hashtags.setText(format_hashtags(content.hashtags))
            if content.tags:
                self.edit_tags.setText(", ".join(content.tags))

    @Slot()
    def _on_paste_tiktok(self) -> None:
        clip = QGuiApplication.clipboard()
        text = clip.text().strip()
        if text:
            self.input_url.setText(text)

    @Slot()
    def _on_browse_download_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu video", self.edit_download_dir.text()
        )
        if folder:
            self.edit_download_dir.setText(folder)
            if self.services.settings:
                self.services.settings.set("download_dir", folder)

    @Slot()
    def _on_open_download_folder(self) -> None:
        p = Path(self.edit_download_dir.text()).resolve()
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    @Slot()
    def _on_download_tiktok(self) -> None:
        url = self.input_url.text().strip()
        if not url:
            self._notify("warning", "Thiếu liên kết", "Vui lòng nhập liên kết video TikTok.")
            return

        dest_dir = Path(self.edit_download_dir.text()).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

        self.btn_download.setEnabled(False)
        self.btn_cancel_download.setVisible(True)
        self.progress_download.setVisible(True)
        self.progress_download.setValue(10)

        # Fetch metadata then download
        worker_meta = FetchMetaWorker(self.services.tiktok, url)
        worker_meta.signals.finished.connect(lambda meta: self._start_video_download(meta, dest_dir))
        worker_meta.signals.error.connect(self._on_tiktok_error)
        self.thread_pool.start(worker_meta)

    def _start_video_download(self, meta: VideoMeta, dest_dir: Path) -> None:
        self.progress_download.setValue(30)
        worker = DownloadVideoWorker(self.services.tiktok, meta, dest_dir)
        self._active_download_worker = worker

        worker.signals.progress.connect(lambda p: self.progress_download.setValue(int(30 + p * 70)))
        worker.signals.finished.connect(self._on_download_finished)
        worker.signals.error.connect(self._on_tiktok_error)
        worker.signals.cancelled.connect(self._on_download_cancelled)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_download_finished(self, result: DownloadResult) -> None:
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.progress_download.setValue(100)
        self._active_download_worker = None

        # Add to table
        file_path = Path(result.path)
        size_mb = f"{file_path.stat().st_size / (1024 * 1024):.1f} MB" if file_path.exists() else "-"
        video_id = result.meta.video_id if result.meta else file_path.stem
        title = result.meta.title if result.meta else file_path.name
        duration = f"{result.meta.duration}s" if result.meta and result.meta.duration else "-"

        row = self.tbl_downloads.rowCount()
        self.tbl_downloads.insertRow(row)
        self.tbl_downloads.setItem(row, 0, QTableWidgetItem(video_id))
        self.tbl_downloads.setItem(row, 1, QTableWidgetItem(title))
        self.tbl_downloads.setItem(row, 2, QTableWidgetItem(duration))
        self.tbl_downloads.setItem(row, 3, QTableWidgetItem(size_mb))
        self.tbl_downloads.setItem(row, 4, QTableWidgetItem(str(file_path)))

        self._downloaded_files.append({
            "video_id": video_id,
            "title": title,
            "duration": duration,
            "size": size_mb,
            "path": str(file_path),
            "meta": result.meta,
        })

        self._notify("success", "Tải hoàn tất", f"Video đã được tải về: {file_path.name}")

    @Slot()
    def _on_cancel_download(self) -> None:
        if self._active_download_worker:
            self._active_download_worker.cancel()

    @Slot()
    def _on_download_cancelled(self) -> None:
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.progress_download.setVisible(False)
        self._active_download_worker = None
        self._notify("info", "Đã hủy", "Đã hủy thao tác tải video TikTok.")

    @Slot(str)
    def _on_tiktok_error(self, err: str) -> None:
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.progress_download.setVisible(False)
        self._active_download_worker = None
        self._notify("error", "Lỗi tải video", err)

    @Slot()
    def _on_pick_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file MP4", "", "Video Files (*.mp4 *.mkv *.mov *.avi)"
        )
        if file_path:
            p = Path(file_path)
            row = self.tbl_downloads.rowCount()
            self.tbl_downloads.insertRow(row)
            self.tbl_downloads.setItem(row, 0, QTableWidgetItem(p.stem))
            self.tbl_downloads.setItem(row, 1, QTableWidgetItem(p.name))
            self.tbl_downloads.setItem(row, 2, QTableWidgetItem("-"))
            size_mb = f"{p.stat().st_size / (1024 * 1024):.1f} MB" if p.exists() else "-"
            self.tbl_downloads.setItem(row, 3, QTableWidgetItem(size_mb))
            self.tbl_downloads.setItem(row, 4, QTableWidgetItem(str(p)))

            self._downloaded_files.append({
                "video_id": p.stem,
                "title": p.name,
                "duration": "-",
                "size": size_mb,
                "path": str(p),
                "meta": None,
            })
            self._notify("success", "Đã thêm tệp", f"Đã chọn: {p.name}")

    @Slot()
    def _on_load_selected_to_job(self) -> None:
        row = self.tbl_downloads.currentRow()
        if row < 0 or row >= len(self._downloaded_files):
            self._notify("warning", "Chưa chọn video", "Vui lòng chọn một dòng video trong bảng để nạp.")
            return

        item_data = self._downloaded_files[row]
        file_path = Path(item_data["path"])
        if not file_path.exists():
            self._notify("error", "Tệp không tồn tại", f"Không tìm thấy file: {file_path}")
            return

        meta = item_data.get("meta")
        if meta:
            self.state.meta = meta
            self.state.title = meta.title
        else:
            self.state.meta = VideoMeta(
                video_id=item_data["video_id"],
                url="",
                title=item_data["title"],
                description=f"Tải lên từ tập tin cục bộ: {file_path.name}",
                author="Cục bộ",
                thumbnail_url=None,
                duration=0.0,
                width=1080,
                height=1920,
            )
            self.state.title = item_data["title"]

        self.state.local_video_path = file_path
        self.state.video_ready.emit(str(file_path))
        self._notify("success", "Đã nạp vào Tổng quan", f"Video '{file_path.name}' đã sẵn sàng trong quy trình chính.")

    @Slot()
    def _on_open_selected_video(self) -> None:
        row = self.tbl_downloads.currentRow()
        if row < 0 or row >= len(self._downloaded_files):
            return
        item_data = self._downloaded_files[row]
        p = Path(item_data["path"])
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    # =========================================================================
    # LOGIC & SLOTS: AI GENERATOR
    # =========================================================================
    @Slot()
    def _on_pull_from_current_job(self) -> None:
        if self.state.meta:
            self.edit_ai_orig_title.setText(self.state.meta.title or "")
            self.edit_ai_orig_desc.setPlainText(self.state.meta.description or "")
            self._notify("info", "Đã lấy thông tin", "Đã điền tiêu đề và mô tả từ tác vụ hiện tại.")
        elif self.state.title:
            self.edit_ai_orig_title.setText(self.state.title)
            self._notify("info", "Đã lấy thông tin", "Đã điền tiêu đề từ tác vụ hiện tại.")
        else:
            self._notify("warning", "Chưa có dữ liệu", "Tác vụ hiện tại chưa có thông tin video nào.")

    @Slot()
    def _on_generate_ai_clicked(self) -> None:
        orig_title = self.edit_ai_orig_title.text().strip()
        orig_desc = self.edit_ai_orig_desc.toPlainText().strip()
        if not orig_title and not orig_desc:
            self._notify("warning", "Thiếu thông tin", "Vui lòng nhập ít nhất tiêu đề hoặc mô tả gốc.")
            return

        self.btn_generate_ai.setEnabled(False)
        self.progress_ai.setVisible(True)
        self.progress_ai.setValue(20)

        meta = VideoMeta(
            video_id="standalone-ai",
            url="",
            title=orig_title or "Video TikTok",
            description=orig_desc,
            author="User",
            thumbnail_url=None,
            duration=60.0,
            width=1080,
            height=1920,
        )

        settings = {
            "model": self.combo_model.currentText(),
            "tone": self.combo_tone.currentData(),
        }

        worker = GenerateContentWorker(self.services.generator, meta, settings)
        self._active_ai_worker = worker
        worker.signals.finished.connect(self._on_ai_finished)
        worker.signals.error.connect(self._on_ai_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_ai_finished(self, content: GeneratedContent) -> None:
        self.btn_generate_ai.setEnabled(True)
        self.progress_ai.setVisible(False)
        self._active_ai_worker = None

        self.edit_title.setText(content.title)
        self.edit_desc.setPlainText(content.description)
        self.edit_hashtags.setText(format_hashtags(content.hashtags))
        self.edit_tags.setText(", ".join(content.tags))

        self._notify("success", "Tạo nội dung thành công", "AI đã sinh xong tiêu đề, mô tả và từ khóa mới.")

    @Slot(str)
    def _on_ai_error(self, err: str) -> None:
        self.btn_generate_ai.setEnabled(True)
        self.progress_ai.setVisible(False)
        self._active_ai_worker = None
        self._notify("error", "Lỗi sinh nội dung AI", err)

    def _update_title_counter(self, text: str) -> None:
        count = len(text)
        self.lbl_title_counter.setText(f"{count}/100 ký tự")
        if count > 100:
            self.lbl_title_counter.setProperty("class", "charCounterDanger")
        elif count >= 90:
            self.lbl_title_counter.setProperty("class", "charCounterWarn")
        else:
            self.lbl_title_counter.setProperty("class", "charCounter")
        self.lbl_title_counter.style().unpolish(self.lbl_title_counter)
        self.lbl_title_counter.style().polish(self.lbl_title_counter)

    def _copy_to_clip(self, text: str, name: str) -> None:
        if not text:
            return
        clip = QGuiApplication.clipboard()
        clip.setText(text)
        self._notify("info", "Đã sao chép", f"Đã sao chép {name} vào bộ nhớ tạm.")

    @Slot()
    def _on_copy_all_ai(self) -> None:
        parts = []
        if self.edit_title.text():
            parts.append(f"Tiêu đề:\n{self.edit_title.text()}\n")
        if self.edit_desc.toPlainText():
            parts.append(f"Mô tả:\n{self.edit_desc.toPlainText()}\n")
        if self.edit_hashtags.text():
            parts.append(f"Hashtags:\n{self.edit_hashtags.text()}\n")
        if self.edit_tags.text():
            parts.append(f"Tags:\n{self.edit_tags.text()}\n")

        if not parts:
            self._notify("warning", "Trống", "Chưa có nội dung nào để sao chép.")
            return

        clip = QGuiApplication.clipboard()
        clip.setText("\n".join(parts))
        self._notify("info", "Đã sao chép tất cả", "Đã sao chép toàn bộ nội dung AI vào bộ nhớ tạm.")

    @Slot()
    def _on_apply_ai_to_job(self) -> None:
        if not self.edit_title.text():
            self._notify("warning", "Chưa có nội dung", "Vui lòng tạo nội dung trước khi áp dụng.")
            return

        self.state.title = self.edit_title.text()
        self.state.description = self.edit_desc.toPlainText()
        raw_hash = self.edit_hashtags.text().replace("#", " ").split()
        self.state.hashtags = [h.strip() for h in raw_hash if h.strip()]
        self.state.tags = [t.strip() for t in self.edit_tags.text().split(",") if t.strip()]

        self._notify("success", "Đã áp dụng", "Nội dung AI đã được chuyển sang quy trình Tổng quan.")
