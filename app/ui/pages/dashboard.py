"""Dashboard page: 4-step streamlined workflow for TikTok to YouTube automation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Slot
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.contracts import DownloadResult, GeneratedContent, VideoMeta
from app.ui.components import Card, UploadConfirmDialog, VideoPlayerWidget
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import (
    DownloadVideoWorker, FetchMetaWorker, GenerateContentWorker,
    UploadYouTubeWorker,
)


class DashboardPage(QWidget):
    """The main 4-step workflow dashboard: TikTok -> Preview -> AI -> YouTube."""

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
        self._active_upload_worker: Optional[UploadYouTubeWorker] = None

        self._init_ui()
        self._connect_state()
        self._refresh_channel_info()

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area to comfortably fit 1080p and 720p screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Page Header
        header_layout = QHBoxLayout()
        header_title = QLabel("Quy trình 4 bước chuyển đổi Video", container)
        header_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        self.btn_reset_job = QPushButton("Làm mới tác vụ", container)
        self.btn_reset_job.clicked.connect(self._on_reset_clicked)
        header_layout.addWidget(self.btn_reset_job)
        layout.addLayout(header_layout)

        # ==========================================
        # BƯỚC 1: TIKTOK
        # ==========================================
        self.step1_card = Card(
            step_number=1,
            title="TikTok Downloader",
            subtitle="Nhập liên kết video TikTok hoặc chọn video có sẵn từ máy tính",
            parent=container,
        )

        s1_layout = QVBoxLayout()
        s1_layout.setSpacing(10)

        # URL Input row
        url_row = QHBoxLayout()
        url_row.setSpacing(8)

        self.input_url = QLineEdit(self.step1_card)
        self.input_url.setPlaceholderText("https://www.tiktok.com/@user/video/...")
        self.input_url.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.input_url, stretch=1)

        self.btn_paste = QPushButton("Dán", self.step1_card)
        self.btn_paste.clicked.connect(self._on_paste_clicked)
        url_row.addWidget(self.btn_paste)

        self.btn_download = QPushButton("Tải video", self.step1_card)
        self.btn_download.setProperty("class", "primaryBtn")
        self.btn_download.clicked.connect(self._on_download_clicked)
        url_row.addWidget(self.btn_download)

        self.btn_pick_file = QPushButton("Chọn MP4 từ máy", self.step1_card)
        self.btn_pick_file.clicked.connect(self._on_pick_file_clicked)
        url_row.addWidget(self.btn_pick_file)

        s1_layout.addLayout(url_row)

        # Download Progress and cancel
        progress_row = QHBoxLayout()
        self.progress_download = QProgressBar(self.step1_card)
        self.progress_download.setRange(0, 100)
        self.progress_download.setValue(0)
        self.progress_download.setVisible(False)
        progress_row.addWidget(self.progress_download, stretch=1)

        self.btn_cancel_download = QPushButton("Hủy tải", self.step1_card)
        self.btn_cancel_download.setProperty("class", "dangerBtn")
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download)
        progress_row.addWidget(self.btn_cancel_download)
        s1_layout.addLayout(progress_row)

        # TikTok Meta Info Preview Box
        self.tiktok_meta_box = QFrame(self.step1_card)
        self.tiktok_meta_box.setStyleSheet(
            "background-color: #12141e; border: 1px solid #232736; border-radius: 8px; padding: 10px;"
        )
        self.tiktok_meta_box.setVisible(False)
        meta_layout = QGridLayout(self.tiktok_meta_box)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.setSpacing(6)

        self.lbl_meta_title = QLabel("Tiêu đề: -")
        self.lbl_meta_title.setStyleSheet("font-weight: 600; color: #f8fafc;")
        meta_layout.addWidget(self.lbl_meta_title, 0, 0, 1, 2)

        self.lbl_meta_author = QLabel("Tác giả: -")
        self.lbl_meta_author.setProperty("class", "hintLabel")
        meta_layout.addWidget(self.lbl_meta_author, 1, 0)

        self.lbl_meta_duration = QLabel("Thời lượng: -")
        self.lbl_meta_duration.setProperty("class", "hintLabel")
        meta_layout.addWidget(self.lbl_meta_duration, 1, 1)

        self.lbl_meta_resolution = QLabel("Độ phân giải: -")
        self.lbl_meta_resolution.setProperty("class", "hintLabel")
        meta_layout.addWidget(self.lbl_meta_resolution, 2, 0)

        self.lbl_meta_status = QLabel("Trạng thái: Chưa tải")
        self.lbl_meta_status.setStyleSheet("color: #38bdf8; font-weight: 600;")
        meta_layout.addWidget(self.lbl_meta_status, 2, 1)

        s1_layout.addWidget(self.tiktok_meta_box)
        self.step1_card.add_layout(s1_layout)
        layout.addWidget(self.step1_card)

        # ==========================================
        # BƯỚC 2: PREVIEW
        # ==========================================
        self.step2_card = Card(
            step_number=2,
            title="Xem trước Video (Preview)",
            subtitle="Trình phát video trực quan: phát, dừng và tua dòng thời gian",
            parent=container,
        )
        self.player_widget = VideoPlayerWidget(self.step2_card)
        self.step2_card.add_widget(self.player_widget)
        layout.addWidget(self.step2_card)

        # ==========================================
        # BƯỚC 3: AI
        # ==========================================
        self.step3_card = Card(
            step_number=3,
            title="Tối ưu nội dung bằng AI (Gemini)",
            subtitle="Tự động sinh tiêu đề chuẩn SEO, mô tả hấp dẫn, hashtag và thẻ phân loại",
            parent=container,
        )

        s3_layout = QVBoxLayout()
        s3_layout.setSpacing(12)

        # Model row + Generate Button
        ai_top_row = QHBoxLayout()
        ai_top_row.setSpacing(10)

        lbl_model = QLabel("Mô hình AI:", self.step3_card)
        lbl_model.setProperty("class", "fieldLabel")
        ai_top_row.addWidget(lbl_model)

        self.combo_model = QComboBox(self.step3_card)
        self._populate_models()
        ai_top_row.addWidget(self.combo_model)

        self.btn_generate_ai = QPushButton("✨ Tạo nội dung AI", self.step3_card)
        self.btn_generate_ai.setProperty("class", "primaryBtn")
        self.btn_generate_ai.clicked.connect(self._on_generate_clicked)
        ai_top_row.addWidget(self.btn_generate_ai)

        self.btn_restore_original = QPushButton("Khôi phục gốc", self.step3_card)
        self.btn_restore_original.clicked.connect(self._on_restore_original_clicked)
        ai_top_row.addWidget(self.btn_restore_original)

        self.btn_copy_all = QPushButton("Sao chép", self.step3_card)
        self.btn_copy_all.clicked.connect(self._on_copy_all_clicked)
        ai_top_row.addWidget(self.btn_copy_all)

        ai_top_row.addStretch()
        s3_layout.addLayout(ai_top_row)

        # AI Progress Bar
        self.progress_ai = QProgressBar(self.step3_card)
        self.progress_ai.setRange(0, 100)
        self.progress_ai.setValue(0)
        self.progress_ai.setVisible(False)
        s3_layout.addWidget(self.progress_ai)

        # Title Editor with /100 counter
        title_header = QHBoxLayout()
        lbl_title_field = QLabel("Tiêu đề YouTube:", self.step3_card)
        lbl_title_field.setProperty("class", "fieldLabel")
        title_header.addWidget(lbl_title_field)

        title_header.addStretch()

        self.lbl_title_counter = QLabel("0/100 ký tự", self.step3_card)
        self.lbl_title_counter.setProperty("class", "charCounter")
        title_header.addWidget(self.lbl_title_counter)
        s3_layout.addLayout(title_header)

        self.edit_title = QLineEdit(self.step3_card)
        self.edit_title.setPlaceholderText("Tiêu đề tối đa 100 ký tự...")
        self.edit_title.textChanged.connect(self._on_title_changed)
        s3_layout.addWidget(self.edit_title)

        # Description Editor
        lbl_desc_field = QLabel("Mô tả video:", self.step3_card)
        lbl_desc_field.setProperty("class", "fieldLabel")
        s3_layout.addWidget(lbl_desc_field)

        self.edit_desc = QTextEdit(self.step3_card)
        self.edit_desc.setPlaceholderText("Nhập mô tả video...")
        self.edit_desc.setMinimumHeight(90)
        self.edit_desc.textChanged.connect(self._on_desc_changed)
        s3_layout.addWidget(self.edit_desc)

        # Hashtags and Tags row
        tags_grid = QGridLayout()
        tags_grid.setSpacing(10)

        lbl_hash = QLabel("Hashtags (cách nhau bởi dấu cách hoặc phẩy):", self.step3_card)
        lbl_hash.setProperty("class", "fieldLabel")
        tags_grid.addWidget(lbl_hash, 0, 0)

        self.edit_hashtags = QLineEdit(self.step3_card)
        self.edit_hashtags.setPlaceholderText("shorts, trending, fyp...")
        self.edit_hashtags.textChanged.connect(self._on_hashtags_changed)
        tags_grid.addWidget(self.edit_hashtags, 1, 0)

        lbl_tags = QLabel("Thẻ tìm kiếm (Tags):", self.step3_card)
        lbl_tags.setProperty("class", "fieldLabel")
        tags_grid.addWidget(lbl_tags, 0, 1)

        self.edit_tags = QLineEdit(self.step3_card)
        self.edit_tags.setPlaceholderText("hài hước, video ngắn...")
        self.edit_tags.textChanged.connect(self._on_tags_changed)
        tags_grid.addWidget(self.edit_tags, 1, 1)

        s3_layout.addLayout(tags_grid)
        self.step3_card.add_layout(s3_layout)
        layout.addWidget(self.step3_card)

        # ==========================================
        # BƯỚC 4: YOUTUBE
        # ==========================================
        self.step4_card = Card(
            step_number=4,
            title="Đăng tải lên YouTube",
            subtitle="Thiết lập quyền riêng tư, đối tượng người xem và xác nhận quyền sở hữu",
            parent=container,
        )

        s4_layout = QVBoxLayout()
        s4_layout.setSpacing(14)

        # Connected Channel display
        self.channel_box = QFrame(self.step4_card)
        self.channel_box.setStyleSheet(
            "background-color: #12141e; border: 1px solid #232736; border-radius: 8px; padding: 12px;"
        )
        ch_layout = QHBoxLayout(self.channel_box)
        ch_layout.setContentsMargins(8, 8, 8, 8)

        ch_icon = QLabel("🔴")
        ch_icon.setStyleSheet("font-size: 16px;")
        ch_layout.addWidget(ch_icon)

        ch_text_box = QVBoxLayout()
        self.lbl_channel_title = QLabel("Kênh YouTube: Đang kiểm tra...")
        self.lbl_channel_title.setStyleSheet("font-weight: 600; color: #f8fafc;")
        ch_text_box.addWidget(self.lbl_channel_title)

        self.lbl_channel_id = QLabel("ID kênh: -")
        self.lbl_channel_id.setProperty("class", "hintLabel")
        ch_text_box.addWidget(self.lbl_channel_id)
        ch_layout.addLayout(ch_text_box, stretch=1)

        self.btn_refresh_channel = QPushButton("Làm mới kênh", self.channel_box)
        self.btn_refresh_channel.clicked.connect(self._refresh_channel_info)
        ch_layout.addWidget(self.btn_refresh_channel)
        s4_layout.addWidget(self.channel_box)

        # Settings Form: Privacy and Made for Kids
        form_grid = QGridLayout()
        form_grid.setSpacing(14)

        # Privacy
        lbl_privacy = QLabel("Chế độ hiển thị (Privacy):", self.step4_card)
        lbl_privacy.setProperty("class", "fieldLabel")
        form_grid.addWidget(lbl_privacy, 0, 0)

        self.combo_privacy = QComboBox(self.step4_card)
        self.combo_privacy.addItem("Riêng tư (Private) - Mặc định an toàn", "private")
        self.combo_privacy.addItem("Không công khai (Unlisted)", "unlisted")
        self.combo_privacy.addItem("Công khai (Public)", "public")
        self.combo_privacy.setCurrentIndex(0)  # Default: Private
        self.combo_privacy.currentIndexChanged.connect(self._on_privacy_changed)
        form_grid.addWidget(self.combo_privacy, 1, 0)

        # Made for Kids: KHÔNG CHỌN SẴN, BẮT BUỘC CHỌN
        lbl_kids = QLabel("Nội dung dành cho trẻ em? (Bắt buộc chọn):", self.step4_card)
        lbl_kids.setProperty("class", "fieldLabel")
        form_grid.addWidget(lbl_kids, 0, 1)

        kids_btn_box = QHBoxLayout()
        self.radio_kids_yes = QRadioButton("Có, dành cho trẻ em", self.step4_card)
        self.radio_kids_no = QRadioButton("Không, không dành cho trẻ em", self.step4_card)
        self.kids_group = QButtonGroup(self.step4_card)
        self.kids_group.addButton(self.radio_kids_yes, 1)
        self.kids_group.addButton(self.radio_kids_no, 0)
        # Note: Do NOT check any button initially!
        self.radio_kids_yes.toggled.connect(self._on_kids_changed)
        self.radio_kids_no.toggled.connect(self._on_kids_changed)

        kids_btn_box.addWidget(self.radio_kids_yes)
        kids_btn_box.addWidget(self.radio_kids_no)
        kids_btn_box.addStretch()
        form_grid.addLayout(kids_btn_box, 1, 1)

        s4_layout.addLayout(form_grid)

        # Checkbox: "Tôi xác nhận có quyền sử dụng video này" (BẮT BUỘC)
        self.chk_rights = QCheckBox(
            "Tôi xác nhận có quyền sử dụng video này và chịu hoàn toàn trách nhiệm về bản quyền.",
            self.step4_card,
        )
        self.chk_rights.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.chk_rights.toggled.connect(self._on_rights_changed)
        s4_layout.addWidget(self.chk_rights)

        # Checkbox: Chế độ Dry-run
        self.chk_dry_run = QCheckBox(
            "🧪 Chế độ chạy thử (Dry-run) - Chạy toàn bộ luồng nhưng không gọi tải lên YouTube thật",
            self.step4_card,
        )
        self.chk_dry_run.setStyleSheet("color: #93c5fd;")
        self.chk_dry_run.toggled.connect(self._on_dry_run_toggled)
        s4_layout.addWidget(self.chk_dry_run)

        # Upload Action Bar
        upload_action_row = QHBoxLayout()
        upload_action_row.setSpacing(12)

        self.btn_upload = QPushButton("🚀 Tải lên YouTube", self.step4_card)
        self.btn_upload.setProperty("class", "primaryBtn")
        self.btn_upload.setMinimumHeight(40)
        self.btn_upload.setEnabled(False)  # Disabled until rights & kids & title are valid
        self.btn_upload.clicked.connect(self._on_upload_clicked)
        upload_action_row.addWidget(self.btn_upload, stretch=1)

        self.btn_cancel_upload = QPushButton("Hủy đăng", self.step4_card)
        self.btn_cancel_upload.setProperty("class", "dangerBtn")
        self.btn_cancel_upload.setMinimumHeight(40)
        self.btn_cancel_upload.setVisible(False)
        self.btn_cancel_upload.clicked.connect(self._on_cancel_upload)
        upload_action_row.addWidget(self.btn_cancel_upload)

        s4_layout.addLayout(upload_action_row)

        # Upload Progress Bar
        self.progress_upload = QProgressBar(self.step4_card)
        self.progress_upload.setRange(0, 100)
        self.progress_upload.setValue(0)
        self.progress_upload.setVisible(False)
        s4_layout.addWidget(self.progress_upload)

        # Upload Result Box
        self.upload_result_box = QFrame(self.step4_card)
        self.upload_result_box.setStyleSheet(
            "background-color: #064e3b; border: 1px solid #059669; border-radius: 8px; padding: 12px;"
        )
        self.upload_result_box.setVisible(False)
        res_layout = QVBoxLayout(self.upload_result_box)
        res_layout.setSpacing(8)

        self.lbl_upload_status = QLabel("✅ Tải lên thành công!")
        self.lbl_upload_status.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 14px;")
        res_layout.addWidget(self.lbl_upload_status)

        self.lbl_upload_url = QLabel("Link: -")
        self.lbl_upload_url.setStyleSheet("color: #a7f3d0;")
        res_layout.addWidget(self.lbl_upload_url)

        res_btn_row = QHBoxLayout()
        res_btn_row.setSpacing(8)

        self.btn_open_youtube = QPushButton("Mở YouTube", self.upload_result_box)
        self.btn_open_youtube.clicked.connect(self._on_open_youtube_clicked)
        res_btn_row.addWidget(self.btn_open_youtube)

        self.btn_copy_link = QPushButton("Sao chép liên kết", self.upload_result_box)
        self.btn_copy_link.clicked.connect(self._on_copy_link_clicked)
        res_btn_row.addWidget(self.btn_copy_link)
        res_btn_row.addStretch()

        res_layout.addLayout(res_btn_row)
        s4_layout.addWidget(self.upload_result_box)

        self.step4_card.add_layout(s4_layout)
        layout.addWidget(self.step4_card)

        # Add bottom stretch
        layout.addStretch()

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def _populate_models(self) -> None:
        try:
            models = self.services.generator.list_models()
        except Exception:
            models = ["gemini-2.0-flash", "gemini-1.5-pro"]
        self.combo_model.clear()
        for m in models:
            self.combo_model.addItem(m, m)

    def _connect_state(self) -> None:
        self.state.job_changed.connect(self._sync_from_state)
        self.state.video_ready.connect(self._on_video_ready)
        self.state.upload_changed.connect(self._on_upload_result)

    # ---------------------------------------------------------
    # State synchronization
    # ---------------------------------------------------------
    def _sync_from_state(self) -> None:
        """Update widget values from shared JobState if changed outside."""
        if self.input_url.text() != self.state.url:
            self.input_url.blockSignals(True)
            self.input_url.setText(self.state.url)
            self.input_url.blockSignals(False)

        # Update metadata card
        if self.state.meta:
            self.tiktok_meta_box.setVisible(True)
            self.lbl_meta_title.setText(f"Tiêu đề: {self.state.meta.title}")
            self.lbl_meta_author.setText(f"Tác giả: {self.state.meta.author}")
            dur = f"{self.state.meta.duration}s" if self.state.meta.duration else "Không rõ"
            self.lbl_meta_duration.setText(f"Thời lượng: {dur}")
            res = (
                f"{self.state.meta.width}x{self.state.meta.height}"
                if self.state.meta.width and self.state.meta.height
                else "Không rõ"
            )
            self.lbl_meta_resolution.setText(f"Độ phân giải: {res}")
            self.lbl_meta_status.setText(f"Trạng thái: {self.state.status.value}")

        # Update title editor
        if self.edit_title.text() != self.state.title:
            self.edit_title.blockSignals(True)
            self.edit_title.setText(self.state.title)
            self.edit_title.blockSignals(False)
            self._update_title_counter(self.state.title)

        # Update description editor
        if self.edit_desc.toPlainText() != self.state.description:
            self.edit_desc.blockSignals(True)
            self.edit_desc.setPlainText(self.state.description)
            self.edit_desc.blockSignals(False)

        # Update tags
        hash_str = " ".join(self.state.hashtags)
        if self.edit_hashtags.text() != hash_str:
            self.edit_hashtags.blockSignals(True)
            self.edit_hashtags.setText(hash_str)
            self.edit_hashtags.blockSignals(False)

        tag_str = ", ".join(self.state.tags)
        if self.edit_tags.text() != tag_str:
            self.edit_tags.blockSignals(True)
            self.edit_tags.setText(tag_str)
            self.edit_tags.blockSignals(False)

        # Update privacy
        idx = self.combo_privacy.findData(self.state.privacy)
        if idx >= 0 and self.combo_privacy.currentIndex() != idx:
            self.combo_privacy.blockSignals(True)
            self.combo_privacy.setCurrentIndex(idx)
            self.combo_privacy.blockSignals(False)

        # Update Made for Kids
        self.radio_kids_yes.blockSignals(True)
        self.radio_kids_no.blockSignals(True)
        if self.state.made_for_kids is True:
            self.radio_kids_yes.setChecked(True)
        elif self.state.made_for_kids is False:
            self.radio_kids_no.setChecked(True)
        else:
            self.kids_group.setExclusive(False)
            self.radio_kids_yes.setChecked(False)
            self.radio_kids_no.setChecked(False)
            self.kids_group.setExclusive(True)
        self.radio_kids_yes.blockSignals(False)
        self.radio_kids_no.blockSignals(False)

        # Update Rights checkbox
        if self.chk_rights.isChecked() != self.state.rights_confirmed:
            self.chk_rights.blockSignals(True)
            self.chk_rights.setChecked(self.state.rights_confirmed)
            self.chk_rights.blockSignals(False)

        # Update Dry-run checkbox
        if self.chk_dry_run.isChecked() != self.state.dry_run:
            self.chk_dry_run.blockSignals(True)
            self.chk_dry_run.setChecked(self.state.dry_run)
            self.chk_dry_run.blockSignals(False)

        self._update_upload_button_state()

    def _update_title_counter(self, text: str) -> None:
        count = len(text)
        self.lbl_title_counter.setText(f"{count}/100 ký tự")
        if count > 100:
            self.lbl_title_counter.setProperty("class", "charCounterDanger")
        elif count >= 90:
            self.lbl_title_counter.setProperty("class", "charCounterWarn")
        else:
            self.lbl_title_counter.setProperty("class", "charCounter")
        # Trigger style reload on label
        self.lbl_title_counter.style().unpolish(self.lbl_title_counter)
        self.lbl_title_counter.style().polish(self.lbl_title_counter)

    # ---------------------------------------------------------
    # Handlers: Step 1 TikTok
    # ---------------------------------------------------------
    @Slot(str)
    def _on_url_changed(self, text: str) -> None:
        self.state.url = text.strip()

    @Slot()
    def _on_paste_clicked(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.input_url.setText(text)
            self.state.url = text

    @Slot()
    def _on_pick_file_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn tập tin video MP4",
            "",
            "Video files (*.mp4 *.mkv *.mov);;Tất cả tập tin (*.*)",
        )
        if file_path:
            p = Path(file_path)
            self.state.set_local_file(p)

    @Slot()
    def _on_download_clicked(self) -> None:
        url = self.state.url or self.input_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập đường dẫn video TikTok trước khi tải.")
            return

        self.btn_download.setEnabled(False)
        self.progress_download.setVisible(True)
        self.progress_download.setValue(10)
        self.btn_cancel_download.setVisible(True)

        # Fetch metadata first
        fetch_worker = FetchMetaWorker(self.services.tiktok, url)
        fetch_worker.signals.finished.connect(self._on_fetch_meta_finished)
        fetch_worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(fetch_worker)

    @Slot(object)
    def _on_fetch_meta_finished(self, meta: VideoMeta) -> None:
        self.state.meta = meta
        dest_dir = Path(".tmp/downloads")
        dest_dir.mkdir(parents=True, exist_ok=True)

        worker = DownloadVideoWorker(self.services.tiktok, meta, dest_dir)
        self._active_download_worker = worker
        worker.signals.progress.connect(self._on_download_progress)
        worker.signals.finished.connect(self._on_download_finished)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.cancelled.connect(self._on_download_cancelled)
        self.thread_pool.start(worker)

    @Slot(float)
    def _on_download_progress(self, p: float) -> None:
        val = int(p * 100)
        self.progress_download.setValue(val)

    @Slot(object)
    def _on_download_finished(self, result: DownloadResult) -> None:
        self.progress_download.setValue(100)
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self._active_download_worker = None
        self.state.set_download_result(result)

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
        QMessageBox.information(self, "Đã hủy", "Đã hủy tiến trình tải video.")

    # ---------------------------------------------------------
    # Handlers: Step 2 Preview
    # ---------------------------------------------------------
    @Slot(str)
    def _on_video_ready(self, path_str: str) -> None:
        self.player_widget.load_video(path_str)

    # ---------------------------------------------------------
    # Handlers: Step 3 AI
    # ---------------------------------------------------------
    @Slot()
    def _on_generate_clicked(self) -> None:
        if not self.state.meta:
            QMessageBox.warning(
                self,
                "Chưa có thông tin",
                "Cần tải video hoặc chọn file MP4 trước khi sinh nội dung AI.",
            )
            return

        self.btn_generate_ai.setEnabled(False)
        self.progress_ai.setVisible(True)
        self.progress_ai.setValue(20)

        model = self.combo_model.currentData() or "gemini-2.0-flash"
        settings = {
            "model": model,
            "video_path": str(self.state.local_video_path) if self.state.local_video_path else None,
        }

        worker = GenerateContentWorker(self.services.generator, self.state.meta, settings)
        worker.signals.progress.connect(lambda p: self.progress_ai.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_generate_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_generate_finished(self, content: GeneratedContent) -> None:
        self.progress_ai.setValue(100)
        self.btn_generate_ai.setEnabled(True)
        self.btn_generate_ai.setText("✨ Tạo lại nội dung")
        self.progress_ai.setVisible(False)
        self.state.set_generated_content(content)

    @Slot()
    def _on_restore_original_clicked(self) -> None:
        self.state.restore_original()

    @Slot()
    def _on_copy_all_clicked(self) -> None:
        clip = QGuiApplication.clipboard()
        text = f"{self.state.title}\n\n{self.state.description}\n\n"
        if self.state.hashtags:
            text += " ".join(f"#{t}" for t in self.state.hashtags) + "\n"
        clip.setText(text)
        QMessageBox.information(self, "Đã sao chép", "Đã sao chép tiêu đề, mô tả và hashtag vào bộ nhớ tạm.")

    @Slot(str)
    def _on_title_changed(self, text: str) -> None:
        self.state.title = text
        self._update_title_counter(text)
        self._update_upload_button_state()

    @Slot()
    def _on_desc_changed(self) -> None:
        self.state.description = self.edit_desc.toPlainText()

    @Slot(str)
    def _on_hashtags_changed(self, text: str) -> None:
        raw = text.replace(",", " ").split()
        self.state.hashtags = [h.lstrip("#") for h in raw if h.strip()]

    @Slot(str)
    def _on_tags_changed(self, text: str) -> None:
        raw = [t.strip() for t in text.split(",") if t.strip()]
        self.state.tags = raw

    # ---------------------------------------------------------
    # Handlers: Step 4 YouTube
    # ---------------------------------------------------------
    @Slot()
    def _refresh_channel_info(self) -> None:
        try:
            ch = self.services.youtube.connect()
            self.lbl_channel_title.setText(f"Kênh YouTube: {ch.title}")
            self.lbl_channel_id.setText(f"ID kênh: {ch.id}")
        except Exception as exc:
            self.lbl_channel_title.setText("Kênh YouTube: Chưa kết nối")
            self.lbl_channel_id.setText(f"Chi tiết: {exc}")

    @Slot(int)
    def _on_privacy_changed(self, index: int) -> None:
        val = self.combo_privacy.itemData(index)
        if val:
            self.state.privacy = val

    @Slot()
    def _on_kids_changed(self) -> None:
        if self.radio_kids_yes.isChecked():
            self.state.made_for_kids = True
        elif self.radio_kids_no.isChecked():
            self.state.made_for_kids = False
        else:
            self.state.made_for_kids = None
        self._update_upload_button_state()

    @Slot(bool)
    def _on_rights_changed(self, checked: bool) -> None:
        self.state.rights_confirmed = checked
        self._update_upload_button_state()

    @Slot(bool)
    def _on_dry_run_toggled(self, checked: bool) -> None:
        self.state.dry_run = checked
        self._update_upload_button_state()

    def _update_upload_button_state(self) -> None:
        """Lock upload button when prerequisites are unmet."""
        title = self.edit_title.text().strip()
        title_ok = 0 < len(title) <= 100 and "<" not in title and ">" not in title
        kids_ok = self.radio_kids_yes.isChecked() or self.radio_kids_no.isChecked()
        rights_ok = self.chk_rights.isChecked()
        has_video = bool(self.state.local_video_path)
        can_click = title_ok and kids_ok and rights_ok and has_video
        self.btn_upload.setEnabled(can_click)
        if self.state.dry_run:
            self.btn_upload.setText("🧪 Chạy thử đăng YouTube (Dry-run)")
        else:
            self.btn_upload.setText("🚀 Tải lên YouTube")

    @Slot()
    def _on_upload_clicked(self) -> None:
        can, reason = self.state.can_upload()
        if not can:
            QMessageBox.warning(self, "Chưa đủ điều kiện đăng", reason)
            return

        try:
            req = self.state.build_upload_request()
            channel = self.services.youtube.get_channel()
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi kiểm tra", str(exc))
            return

        # Explicit confirmation dialog per requirement
        dialog = UploadConfirmDialog(
            req, channel.title, channel.id, self, dry_run=self.state.dry_run
        )
        if dialog.exec() != UploadConfirmDialog.DialogCode.Accepted:
            return  # Cancelled by user in dialog

        # Proceed with upload in background worker
        self.btn_upload.setEnabled(False)
        self.btn_cancel_upload.setVisible(True)
        self.progress_upload.setVisible(True)
        self.progress_upload.setValue(10)

        worker = UploadYouTubeWorker(self.services.youtube, req, dry_run=self.state.dry_run)
        self._active_upload_worker = worker
        worker.signals.progress.connect(lambda p: self.progress_upload.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_upload_finished)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.cancelled.connect(self._on_upload_cancelled)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_upload_finished(self, result) -> None:
        self.progress_upload.setValue(100)
        self.btn_upload.setEnabled(True)
        self.btn_cancel_upload.setVisible(False)
        self._active_upload_worker = None
        self.state.set_upload_result(result)

        # Save to history repository
        try:
            self.services.history.add({
                "video_id": result.video_id,
                "url": result.url,
                "title": self.state.title,
                "status": self.state.status,
                "privacy": self.state.privacy,
            })
        except Exception:
            pass

    @Slot()
    def _on_cancel_upload(self) -> None:
        if self._active_upload_worker:
            self._active_upload_worker.cancel()

    @Slot()
    def _on_upload_cancelled(self) -> None:
        self.btn_upload.setEnabled(True)
        self.btn_cancel_upload.setVisible(False)
        self.progress_upload.setVisible(False)
        self._active_upload_worker = None
        QMessageBox.information(self, "Đã hủy", "Đã hủy quá trình tải lên YouTube.")

    @Slot(object)
    def _on_upload_result(self, result) -> None:
        if result:
            self.upload_result_box.setVisible(True)
            self.lbl_upload_status.setText("✅ Đã đăng thành công lên YouTube!")
            self.lbl_upload_url.setText(f"Liên kết: {result.url}")

    @Slot()
    def _on_open_youtube_clicked(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            QDesktopServices.openUrl(QUrl(self.state.upload_result.url))

    @Slot()
    def _on_copy_link_clicked(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            clip = QGuiApplication.clipboard()
            clip.setText(self.state.upload_result.url)
            QMessageBox.information(self, "Đã sao chép", "Đã sao chép liên kết video YouTube.")

    # ---------------------------------------------------------
    # Common error & reset
    # ---------------------------------------------------------
    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.btn_generate_ai.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_cancel_upload.setVisible(False)
        self.progress_download.setVisible(False)
        self.progress_ai.setVisible(False)
        self.progress_upload.setVisible(False)
        self.state.error_message = message
        QMessageBox.critical(self, "Lỗi tác vụ", f"Đã xảy ra lỗi: {message}")

    @Slot()
    def _on_reset_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "Làm mới tác vụ",
            "Bạn có chắc chắn muốn làm mới toàn bộ dữ liệu đang làm việc không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.reset()
            self.player_widget.clear()
            self.upload_result_box.setVisible(False)
            self.tiktok_meta_box.setVisible(False)
            self.progress_download.setVisible(False)
            self.progress_ai.setVisible(False)
            self.progress_upload.setVisible(False)

