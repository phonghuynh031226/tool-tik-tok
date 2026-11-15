"""Dashboard page: 4-step streamlined workflow for TikTok to YouTube automation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.contracts import DownloadResult, GeneratedContent, JobStatus, VideoMeta
from app.ui.model_loading import populate_models
from app.ui import tokens
from app.ui.components import (
    AppButton, Card, ConfirmDialog, ToastManager, UploadConfirmDialog, VideoPlayerWidget,
    WorkflowStepper,
)
from app.ui.services import ServiceContainer
from app.ui.state import JobState, format_hashtags
from app.workers.service_workers import DryRunResult
from app.workers import (
    AddAccountWorker, DownloadVideoWorker, FetchAccountsWorker, FetchMetaWorker,
    GenerateContentWorker, UploadYouTubeWorker,
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
        self.lbl_model_notice = QLabel(self)
        self.lbl_model_notice.setWordWrap(True)
        self.lbl_model_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.layout().insertWidget(0, self.lbl_model_notice)
        self.services.gemini_selection.changed.connect(self._on_model_selected)
        self._connect_state()
        self.services.add_mode_banner(self)
        self.services.connection.changed.connect(self._refresh_channel_info)
        self._refresh_channel_info()

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area to comfortably fit 1080p and 720p screens
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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

        self.btn_reset_job = AppButton("Làm mới tác vụ", variant="ghost", icon_name="refresh", parent=container)
        self.btn_reset_job.clicked.connect(self._on_reset_clicked)
        header_layout.addWidget(self.btn_reset_job)
        layout.addLayout(header_layout)

        # Stepper for 4-step workflow
        self.stepper = WorkflowStepper(container)
        self.stepper.step_selected.connect(self._scroll_to_step)
        layout.addWidget(self.stepper)

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

        self.btn_paste = AppButton("Dán", variant="secondary", icon_name="content-paste", parent=self.step1_card)
        self.btn_paste.clicked.connect(self._on_paste_clicked)
        url_row.addWidget(self.btn_paste)

        self.btn_download = AppButton("Tải video", variant="primary", icon_name="download", parent=self.step1_card)
        self.btn_download.clicked.connect(self._on_download_clicked)
        url_row.addWidget(self.btn_download)

        self.btn_pick_file = AppButton("Chọn MP4 từ máy", variant="secondary", icon_name="folder-open", parent=self.step1_card)
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

        self.btn_cancel_download = AppButton("Hủy tải", variant="danger", icon_name="close-circle", parent=self.step1_card)
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download)
        progress_row.addWidget(self.btn_cancel_download)
        s1_layout.addLayout(progress_row)

        # TikTok Meta Info Preview Box
        self.tiktok_meta_box = QFrame(self.step1_card)
        self.tiktok_meta_box.setObjectName("tiktokMetaBox")
        self.tiktok_meta_box.setStyleSheet(
            "QFrame#tiktokMetaBox { background-color: #12141e; border: 1px solid #232736; border-radius: 8px; padding: 10px; }"
            "QFrame#tiktokMetaBox QLabel { border: none; background: transparent; }"
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

        self.btn_generate_ai = AppButton("Tạo nội dung AI", variant="primary", icon_name="creation", parent=self.step3_card)
        self.btn_generate_ai.clicked.connect(self._on_generate_clicked)
        ai_top_row.addWidget(self.btn_generate_ai)

        self.btn_restore_original = AppButton("Khôi phục gốc", variant="secondary", icon_name="history", parent=self.step3_card)
        self.btn_restore_original.clicked.connect(self._on_restore_original_clicked)
        ai_top_row.addWidget(self.btn_restore_original)

        self.btn_copy_all = AppButton("Sao chép", variant="secondary", icon_name="content-copy", parent=self.step3_card)
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
        self.channel_box.setObjectName("channelBox")
        self.channel_box.setStyleSheet(
            "QFrame#channelBox { background-color: #12141e; border: 1px solid #232736; border-radius: 8px; padding: 12px; }"
            "QFrame#channelBox QLabel { border: none; background: transparent; }"
        )
        ch_layout = QHBoxLayout(self.channel_box)
        ch_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_channel_indicator = QLabel("●")
        self.lbl_channel_indicator.setStyleSheet("font-size: 16px;")
        ch_layout.addWidget(self.lbl_channel_indicator)

        ch_text_box = QVBoxLayout()
        self.lbl_channel_title = QLabel("Kênh YouTube: Đang kiểm tra...")
        self.lbl_channel_title.setStyleSheet("font-weight: 600; color: #f8fafc;")
        ch_text_box.addWidget(self.lbl_channel_title)

        self.lbl_channel_id = QLabel("ID kênh: -")
        self.lbl_channel_id.setProperty("class", "hintLabel")
        ch_text_box.addWidget(self.lbl_channel_id)
        ch_layout.addLayout(ch_text_box, stretch=1)

        self.btn_refresh_channel = AppButton("Làm mới kênh", variant="ghost", icon_name="refresh", parent=self.channel_box)
        self.btn_refresh_channel.clicked.connect(self._refresh_accounts_async)
        ch_layout.addWidget(self.btn_refresh_channel)
        s4_layout.addWidget(self.channel_box)

        # Channel Selector ComboBox Row
        ch_picker_row = QHBoxLayout()
        self.lbl_choose_channel = QLabel("Chọn tài khoản kênh:", self.step4_card)
        self.lbl_choose_channel.setProperty("class", "fieldLabel")
        ch_picker_row.addWidget(self.lbl_choose_channel)

        self.combo_channel = QComboBox(self.step4_card)
        self.combo_channel.currentIndexChanged.connect(self._on_channel_combo_changed)
        ch_picker_row.addWidget(self.combo_channel, stretch=1)

        self.btn_reconnect_channel = AppButton("Đăng nhập lại", variant="danger", icon_name="refresh", parent=self.step4_card)
        self.btn_reconnect_channel.setVisible(False)
        self.btn_reconnect_channel.clicked.connect(self._on_reconnect_channel_clicked)
        ch_picker_row.addWidget(self.btn_reconnect_channel)
        s4_layout.addLayout(ch_picker_row)

        # Timing Mode: Publish Now vs Scheduled
        timing_row = QHBoxLayout()
        lbl_timing = QLabel("Thời điểm xuất bản:", self.step4_card)
        lbl_timing.setProperty("class", "fieldLabel")
        timing_row.addWidget(lbl_timing)

        self.radio_publish_now = QRadioButton("Đăng ngay", self.step4_card)
        self.radio_publish_now.setChecked(True)
        self.radio_publish_schedule = QRadioButton("Hẹn giờ công khai", self.step4_card)
        self.timing_group = QButtonGroup(self.step4_card)
        self.timing_group.addButton(self.radio_publish_now, 0)
        self.timing_group.addButton(self.radio_publish_schedule, 1)
        self.radio_publish_now.toggled.connect(self._on_timing_changed)
        self.radio_publish_schedule.toggled.connect(self._on_timing_changed)

        timing_row.addWidget(self.radio_publish_now)
        timing_row.addWidget(self.radio_publish_schedule)
        timing_row.addStretch()
        s4_layout.addLayout(timing_row)

        # Schedule Container (Hidden by default until 'Hẹn giờ công khai' is chosen)
        self.schedule_container = QFrame(self.step4_card)
        self.schedule_container.setObjectName("scheduleBox")
        self.schedule_container.setStyleSheet(
            "QFrame#scheduleBox { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; }"
            "QFrame#scheduleBox QLabel { border: none; background: transparent; }"
        )
        self.schedule_container.setVisible(False)
        sc_layout = QVBoxLayout(self.schedule_container)
        sc_layout.setSpacing(8)

        sc_top_row = QHBoxLayout()
        lbl_dt = QLabel("Ngày & Giờ phát hành:", self.schedule_container)
        lbl_dt.setStyleSheet("font-weight: 600; color: #f8fafc;")
        sc_top_row.addWidget(lbl_dt)

        self.dt_publish = QDateTimeEdit(self.schedule_container)
        self.dt_publish.setCalendarPopup(True)
        self.dt_publish.setDisplayFormat("dd/MM/yyyy HH:mm")
        now_dt = datetime.now() + timedelta(hours=1)
        now_dt = now_dt.replace(minute=(now_dt.minute // 5) * 5, second=0, microsecond=0)
        self.dt_publish.setDateTime(now_dt)
        self.dt_publish.dateTimeChanged.connect(self._on_schedule_datetime_changed)
        sc_top_row.addWidget(self.dt_publish)

        tz_str = datetime.now().astimezone().strftime("%z")
        tz_formatted = f"GMT{tz_str[:3]}:{tz_str[3:]}" if len(tz_str) == 5 else "GMT+7"
        self.lbl_timezone = QLabel(f"Múi giờ máy: {tz_formatted}", self.schedule_container)
        self.lbl_timezone.setStyleSheet("color: #38bdf8; font-weight: 500; font-size: 12px;")
        sc_top_row.addWidget(self.lbl_timezone)
        sc_top_row.addStretch()
        sc_layout.addLayout(sc_top_row)

        self.lbl_schedule_error = QLabel(self.schedule_container)
        self.lbl_schedule_error.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600;")
        self.lbl_schedule_error.setVisible(False)
        sc_layout.addWidget(self.lbl_schedule_error)

        self.lbl_schedule_note = QLabel(
            "YouTube sẽ tự động công khai video đúng thời điểm hẹn, bạn không cần giữ ứng dụng chạy.",
            self.schedule_container,
        )
        self.lbl_schedule_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        sc_layout.addWidget(self.lbl_schedule_note)

        s4_layout.addWidget(self.schedule_container)

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

        self.lbl_privacy_hint = QLabel("Đã khóa ở chế độ Riêng tư cho đến giờ hẹn công khai.", self.step4_card)
        self.lbl_privacy_hint.setStyleSheet("color: #38bdf8; font-size: 11px;")
        self.lbl_privacy_hint.setVisible(False)
        form_grid.addWidget(self.lbl_privacy_hint, 2, 0)

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
            "Chế độ chạy thử (Dry-run) - Chạy toàn bộ luồng nhưng không gọi tải lên YouTube thật",
            self.step4_card,
        )
        self.chk_dry_run.setStyleSheet("color: #93c5fd;")
        self.chk_dry_run.toggled.connect(self._on_dry_run_toggled)
        s4_layout.addWidget(self.chk_dry_run)

        # Upload Action Bar
        upload_action_row = QHBoxLayout()
        upload_action_row.setSpacing(12)

        self.btn_upload = AppButton("Tải lên YouTube", variant="primary", icon_name="upload", parent=self.step4_card)
        self.btn_upload.setMinimumHeight(40)
        self.btn_upload.setEnabled(False)  # Disabled until rights & kids & title are valid
        self.btn_upload.clicked.connect(self._on_upload_clicked)
        upload_action_row.addWidget(self.btn_upload, stretch=1)

        self.btn_cancel_upload = AppButton("Hủy đăng", variant="danger", icon_name="close-circle", parent=self.step4_card)
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
        self.upload_result_box.setObjectName("uploadResultBox")
        self.upload_result_box.setStyleSheet(
            "QFrame#uploadResultBox { background-color: #064e3b; border: 1px solid #059669; border-radius: 8px; padding: 12px; }"
            "QFrame#uploadResultBox QLabel { border: none; background: transparent; }"
        )
        self.upload_result_box.setVisible(False)
        res_layout = QVBoxLayout(self.upload_result_box)
        res_layout.setSpacing(8)

        self.lbl_upload_status = QLabel("Tải lên thành công!")
        self.lbl_upload_status.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 14px;")
        res_layout.addWidget(self.lbl_upload_status)
        self.lbl_upload_summary = QLabel(self.upload_result_box)
        self.lbl_upload_summary.setWordWrap(True)
        self.lbl_upload_summary.setTextFormat(Qt.TextFormat.PlainText)
        res_layout.addWidget(self.lbl_upload_summary)

        self.lbl_upload_url = QLabel("Link: -")
        self.lbl_upload_url.setStyleSheet("color: #a7f3d0;")
        res_layout.addWidget(self.lbl_upload_url)

        res_btn_row = QHBoxLayout()
        res_btn_row.setSpacing(8)

        self.btn_open_youtube = AppButton("Mở YouTube", variant="secondary", icon_name="open-in-new", parent=self.upload_result_box)
        self.btn_open_youtube.clicked.connect(self._on_open_youtube_clicked)
        res_btn_row.addWidget(self.btn_open_youtube)

        self.btn_copy_link = AppButton("Sao chép liên kết", variant="secondary", icon_name="content-copy", parent=self.upload_result_box)
        self.btn_copy_link.clicked.connect(self._on_copy_link_clicked)
        res_btn_row.addWidget(self.btn_copy_link)
        res_btn_row.addStretch()

        res_layout.addLayout(res_btn_row)
        s4_layout.addWidget(self.upload_result_box)

        self.step4_card.add_layout(s4_layout)

        # Responsive Grid Layout for 4 steps: 2 columns when wide, 1 column when narrow
        self.steps_grid = QGridLayout()
        self.steps_grid.setSpacing(tokens.SPACE_LG)
        layout.addLayout(self.steps_grid)

        self._is_wide_layout: Optional[bool] = None
        self._update_layout_mode(1200)

        # Add bottom stretch
        layout.addStretch()

        self.scroll_area.setWidget(container)
        outer_layout.addWidget(self.scroll_area)

    def _scroll_to_step(self, step: int) -> None:
        cards = {
            1: self.step1_card,
            2: self.step2_card,
            3: self.step3_card,
            4: self.step4_card,
        }
        card = cards.get(step)
        if card:
            self.scroll_area.ensureWidgetVisible(card)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_layout_mode(event.size().width())

    def _update_layout_mode(self, width: int) -> None:
        """Switch between 2-column layout (>=1150px) and 1-column layout (<1150px)."""
        is_wide = width >= 1150
        if self._is_wide_layout == is_wide:
            return
        self._is_wide_layout = is_wide

        self.steps_grid.removeWidget(self.step1_card)
        self.steps_grid.removeWidget(self.step2_card)
        self.steps_grid.removeWidget(self.step3_card)
        self.steps_grid.removeWidget(self.step4_card)

        if is_wide:
            self.steps_grid.addWidget(self.step1_card, 0, 0)
            self.steps_grid.addWidget(self.step2_card, 1, 0)
            self.steps_grid.addWidget(self.step3_card, 0, 1)
            self.steps_grid.addWidget(self.step4_card, 1, 1)
            self.steps_grid.setColumnStretch(0, 1)
            self.steps_grid.setColumnStretch(1, 1)
        else:
            self.steps_grid.addWidget(self.step1_card, 0, 0)
            self.steps_grid.addWidget(self.step2_card, 1, 0)
            self.steps_grid.addWidget(self.step3_card, 2, 0)
            self.steps_grid.addWidget(self.step4_card, 3, 0)
            self.steps_grid.setColumnStretch(0, 1)
            self.steps_grid.setColumnStretch(1, 0)

    def _populate_models(self) -> None:
        populate_models(self.combo_model, self.services)

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
        hash_str = format_hashtags(self.state.hashtags)
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
        self._update_stepper_state()

    def _update_stepper_state(self) -> None:
        """Update workflow stepper states strictly enforcing sequential progression.

        Sequential Progression Rule:
        Step N is marked 'done' (Hoàn thành) IF AND ONLY IF:
          1. Step N has valid output data, AND
          2. Every preceding step 1..(N-1) is also 'done'.

        A step cannot be 'done' if any earlier step is 'pending' or 'active'.
        This mathematically prevents inconsistent states like:
        - Step 1 'active', Step 2 'pending', Step 3 'done'.
        """
        if not hasattr(self, "stepper"):
            return

        # -------------------------------------------------------------
        # Step 1: Nguồn Video (TikTok URL / File MP4)
        # -------------------------------------------------------------
        step1_has_data = (
            (bool(self.state.local_video_path) and self.state.local_video_path.exists())
            or (bool(self.state.video_path) and self.state.status in (
                JobStatus.DOWNLOADED, JobStatus.CONTENT_READY, JobStatus.UPLOADING, JobStatus.UPLOADED, JobStatus.SCHEDULED
            ))
        )
        step1_done = step1_has_data

        if step1_done:
            self.stepper.set_step_state(1, "done")
        elif self._active_download_worker is not None:
            self.stepper.set_step_state(1, "active")
        elif self.state.url or self.state.meta:
            self.stepper.set_step_state(1, "active")
        else:
            self.stepper.set_step_state(1, "pending")

        # -------------------------------------------------------------
        # Step 2: Xem trước (Video Player Preview)
        # -------------------------------------------------------------
        # Step 2 can ONLY be 'done' if Step 1 is done and video is available
        step2_has_data = bool(self.state.local_video_path or self.state.video_path)
        step2_done = step1_done and step2_has_data

        if step2_done:
            self.stepper.set_step_state(2, "done")
        elif step1_done:
            self.stepper.set_step_state(2, "active")
        else:
            self.stepper.set_step_state(2, "pending")

        # -------------------------------------------------------------
        # Step 3: Tối ưu AI (Title, Description, Tags)
        # -------------------------------------------------------------
        # Step 3 can ONLY be 'done' if Step 1 AND Step 2 are done AND AI content exists
        step3_has_data = (
            bool(self.state.title and self.state.title.strip())
            and (
                self.state.status in (
                    JobStatus.CONTENT_READY, JobStatus.UPLOADING, JobStatus.UPLOADED, JobStatus.SCHEDULED
                )
                or bool(self.state.description)
                or (self.state.meta is not None and self.state.title != self.state.meta.title)
            )
        )
        step3_done = step1_done and step2_done and step3_has_data

        if step3_done:
            self.stepper.set_step_state(3, "done")
        elif step1_done and step2_done:
            if getattr(self, "_active_ai_worker", None) is not None:
                self.stepper.set_step_state(3, "active")
            else:
                self.stepper.set_step_state(3, "pending")
        else:
            self.stepper.set_step_state(3, "pending")

        # -------------------------------------------------------------
        # Step 4: Xuất bản YouTube (Upload / Schedule)
        # -------------------------------------------------------------
        # Step 4 can ONLY be 'done' if Steps 1, 2, AND 3 are done AND upload succeeded/scheduled
        step4_has_data = self.state.status in (JobStatus.UPLOADED, JobStatus.SCHEDULED)
        step4_done = step1_done and step2_done and step3_done and step4_has_data

        if step4_done:
            self.stepper.set_step_state(4, "done")
        elif step1_done and step2_done and step3_done:
            if self._active_upload_worker is not None or self.state.status == JobStatus.UPLOADING:
                self.stepper.set_step_state(4, "active")
            else:
                self.stepper.set_step_state(4, "pending")
        else:
            self.stepper.set_step_state(4, "pending")

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
        self._notify("info", "Đã hủy", "Đã hủy tiến trình tải video.")

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

        # UI Safety watchdog timer (65s)
        self._ai_timer = QTimer(self)
        self._ai_timer.setSingleShot(True)
        self._ai_timer.timeout.connect(self._on_generate_ui_timeout)
        self._ai_timer.start(65000)

        worker = GenerateContentWorker(self.services.generator, self.state.meta, settings)
        worker.signals.model_selected.connect(self.services.gemini_selection.changed)
        worker.signals.progress.connect(lambda p: self.progress_ai.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_generate_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_generate_finished(self, content: GeneratedContent) -> None:
        if hasattr(self, "_ai_timer") and self._ai_timer.isActive():
            self._ai_timer.stop()
        self.progress_ai.setValue(100)
        self.btn_generate_ai.setEnabled(True)
        self.btn_generate_ai.setText("Tạo lại nội dung")
        self.btn_generate_ai.set_icon_name("refresh")
        self.progress_ai.setVisible(False)
        self.state.set_generated_content(content)

    @Slot()
    def _on_generate_ui_timeout(self) -> None:
        if not self.btn_generate_ai.isEnabled():
            self.progress_ai.setVisible(False)
            self.btn_generate_ai.setEnabled(True)
            QMessageBox.critical(
                self,
                "Quá thời gian phản hồi",
                "Quá thời gian chờ tạo nội dung AI (timeout 60 giây). "
                "Thao tác đã bị dừng. Vui lòng kiểm tra lại kết nối mạng hoặc thử lại sau.",
            )

    def _notify(self, toast_type: str, title: str, message: str = "") -> None:
        """Helper to post toast notification or fall back to message box."""
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
        self._notify("info", "Đã sao chép", "Đã sao chép tiêu đề, mô tả và hashtag vào bộ nhớ tạm.")

    @Slot(str)
    def _on_title_changed(self, text: str) -> None:
        self.state.title = text
        self._update_title_counter(text)
        self._update_upload_button_state()
        self._update_stepper_state()



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
    def _refresh_accounts_async(self):
        worker = FetchAccountsWorker(self.services.youtube)
        worker.signals.finished.connect(self.services.connection.set_accounts)
        worker.signals.error.connect(self.services.connection.error)
        self.thread_pool.start(worker)

    @Slot()
    def _refresh_channel_info(self) -> None:
        connection = self.services.connection
        accounts = list(connection.accounts)
        selected = next((a for a in accounts if a.id == connection.selected_channel_id), None)
        channel = connection.channel
        checking = connection.busy and connection._upload_owner is None
        verified = channel is not None and not self.services.is_fake
        state = 'checking' if checking else ('connected' if verified else 'disconnected')
        self.lbl_channel_indicator.setProperty('connectionState', state)
        color = {'checking': '#facc15', 'connected': '#22c55e', 'disconnected': '#ef4444'}[state]
        self.lbl_channel_indicator.setStyleSheet(f'font-size:20px;color:{color};')
        self.combo_channel.blockSignals(True)
        self.combo_channel.clear()
        for account in accounts:
            suffix = ' (Hết hạn)' if account.status == 'expired' else (' (Mặc định)' if account.is_default else '')
            self.combo_channel.addItem(account.title + suffix, account)
        if not accounts:
            self.combo_channel.addItem('Chưa có tài khoản kết nối', None)
        if selected:
            self.combo_channel.setCurrentIndex(next(i for i, a in enumerate(accounts) if a.id == selected.id))
        self.combo_channel.blockSignals(False)
        self.lbl_channel_title.setText(f'Kênh YouTube: {selected.title}' if selected else 'Kênh YouTube: Chưa kết nối')
        self.lbl_channel_id.setText(f'ID kênh: {selected.id}' if selected else 'ID kênh: -')
        if self.state.channel_id != (selected.id if selected else None):
            self.state.channel_id = selected.id if selected else None
        self.btn_reconnect_channel.setVisible(selected is not None and selected.status != 'connected')
        self._update_upload_button_state()
        self._update_stepper_state()

    @Slot(int)
    def _on_channel_combo_changed(self, index: int) -> None:
        acc = self.combo_channel.itemData(index)
        self.state.channel_id = acc.id if acc else None
        self.services.connection.select_channel(acc.id if acc else None)
        self.btn_reconnect_channel.setVisible(acc is not None and acc.status != 'connected')
        self._update_upload_button_state()

    @Slot()
    def _on_reconnect_channel_clicked(self) -> None:
        if hasattr(self.services.youtube, "add_account"):
            worker = AddAccountWorker(self.services.youtube)
            worker.signals.finished.connect(self._on_reconnected_account)
            worker.signals.error.connect(lambda err: ToastManager.instance().error("Kết nối thất bại", err))
            self.thread_pool.start(worker)
        else:
            ToastManager.instance().info("Kết nối lại kênh", "Vui lòng vào trang Kênh YouTube hoặc Cài đặt để kết nối lại tài khoản.")

    @Slot(object)
    def _on_reconnected_account(self, account):
        worker = FetchAccountsWorker(self.services.youtube)
        worker.signals.finished.connect(self.services.connection.set_accounts)
        self.thread_pool.start(worker)

    @Slot(bool)
    def _on_timing_changed(self, _checked: bool) -> None:
        is_scheduled = self.radio_publish_schedule.isChecked()
        self.schedule_container.setVisible(is_scheduled)
        self.lbl_privacy_hint.setVisible(is_scheduled)
        if is_scheduled:
            self.combo_privacy.setCurrentIndex(0)  # Locked to Private
            self.combo_privacy.setEnabled(False)
            self.state.privacy = "private"
        else:
            self.combo_privacy.setEnabled(True)
            self.state.publish_at = None
        self._validate_schedule_time()
        self._update_upload_button_state()

    @Slot()
    def _on_schedule_datetime_changed(self) -> None:
        self._validate_schedule_time()
        self._update_upload_button_state()

    def _validate_schedule_time(self) -> tuple[bool, str]:
        if not hasattr(self, "radio_publish_schedule") or not self.radio_publish_schedule.isChecked():
            if hasattr(self, "lbl_schedule_error"):
                self.lbl_schedule_error.setVisible(False)
            return True, ""

        qdt = self.dt_publish.dateTime()
        local_py = qdt.toPython()
        local_aware = local_py.astimezone()
        utc_dt = local_aware.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)

        min_allowed = now_utc + timedelta(minutes=10)
        max_allowed = now_utc + timedelta(days=365)

        if utc_dt < min_allowed:
            err = "Thời gian hẹn phải từ 10 phút trở lên kể từ thời điểm hiện tại."
            self.lbl_schedule_error.setText(err)
            self.lbl_schedule_error.setVisible(True)
            return False, err
        elif utc_dt > max_allowed:
            err = "Thời gian hẹn tối đa không quá 365 ngày kể từ thời điểm hiện tại."
            self.lbl_schedule_error.setText(err)
            self.lbl_schedule_error.setVisible(True)
            return False, err

        self.lbl_schedule_error.setVisible(False)
        return True, ""

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
        self._update_stepper_state()

    @Slot(bool)
    def _on_rights_changed(self, checked: bool) -> None:
        self.state.rights_confirmed = checked
        self._update_upload_button_state()
        self._update_stepper_state()

    @Slot(bool)
    def _on_dry_run_toggled(self, checked: bool) -> None:
        self.state.dry_run = checked
        self._update_upload_button_state()
        self._update_stepper_state()

    def _update_upload_button_state(self) -> None:
        """Lock upload button when prerequisites are unmet."""
        title = self.edit_title.text().strip()
        title_ok = 0 < len(title) <= 100 and "<" not in title and ">" not in title
        kids_ok = self.radio_kids_yes.isChecked() or self.radio_kids_no.isChecked()
        rights_ok = self.chk_rights.isChecked()
        has_video = bool(self.state.local_video_path)
        valid_sched, _ = self._validate_schedule_time()

        # Channel validity
        sel_acc = self.combo_channel.itemData(self.combo_channel.currentIndex()) if hasattr(self, "combo_channel") else None
        is_expired = getattr(sel_acc, "status", "") == "expired" if sel_acc else False
        has_channel = (sel_acc is not None or self.services.connection.channel is not None or self.state.dry_run)

        can_click = (
            title_ok
            and kids_ok
            and rights_ok
            and has_video
            and valid_sched
            and not is_expired
            and has_channel
            and self.services.upload_enabled(self.state.dry_run)
            and self.state.can_upload()[0]
        )
        self.btn_upload.setEnabled(can_click)
        if self.state.dry_run:
            self.btn_upload.setText("Chạy thử đăng YouTube (Dry-run)")
            self.btn_upload.set_icon_name("flask")
        elif hasattr(self, "radio_publish_schedule") and self.radio_publish_schedule.isChecked():
            self.btn_upload.setText("Lên lịch đăng YouTube")
            self.btn_upload.set_icon_name("calendar-clock")
        else:
            self.btn_upload.setText("Tải lên YouTube")
            self.btn_upload.set_icon_name("upload")

    @Slot()
    def _on_upload_clicked(self) -> None:
        if not self.services.upload_enabled(self.state.dry_run):
            return
        can, reason = self.state.can_upload()
        if not can:
            QMessageBox.warning(self, "Chưa đủ điều kiện đăng", reason)
            return

        is_scheduled = self.radio_publish_schedule.isChecked()
        if is_scheduled:
            valid_sched, err_msg = self._validate_schedule_time()
            if not valid_sched:
                QMessageBox.warning(self, "Thời gian hẹn không hợp lệ", err_msg)
                return
            local_aware = self.dt_publish.dateTime().toPython().astimezone()
            self.state.publish_at = local_aware.astimezone(timezone.utc)
            self.state.privacy = "private"
        else:
            self.state.publish_at = None

        sel_acc = self.combo_channel.itemData(self.combo_channel.currentIndex()) if hasattr(self, "combo_channel") else None
        if sel_acc and hasattr(sel_acc, "id"):
            self.state.channel_id = sel_acc.id

        try:
            req = self.state.build_upload_request()
            channel = self.services.connection.channel
            if sel_acc and hasattr(sel_acc, "title"):
                channel_title = sel_acc.title
                channel_id = sel_acc.id
            elif channel:
                channel_title = channel.title
                channel_id = channel.id
            else:
                channel_title = "Chưa chọn kênh"
                channel_id = "Chạy thử — không đăng video"
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi kiểm tra", str(exc))
            return

        # Explicit confirmation dialog per requirement
        dialog = UploadConfirmDialog(
            req, channel_title, channel_id, self, dry_run=self.state.dry_run
        )
        if dialog.exec() != UploadConfirmDialog.DialogCode.Accepted:
            return  # Cancelled by user in dialog

        # Proceed with upload in background worker
        if not self.services.connection.begin_upload(self):
            return
        self.btn_upload.setEnabled(False)
        self.btn_cancel_upload.setVisible(True)
        self.progress_upload.setVisible(True)
        self.progress_upload.setValue(10)

        worker = UploadYouTubeWorker(
            self.services.youtube,
            req,
            dry_run=self.state.dry_run,
            confirmed_channel_id=channel_id,
            confirmed_channel_title=channel_title,
        )
        self._active_upload_worker = worker
        worker.signals.progress.connect(lambda p: self.progress_upload.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_upload_finished)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.cancelled.connect(self._on_upload_cancelled)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_upload_finished(self, result) -> None:
        self.services.connection.end_upload(self)
        if not isinstance(result, DryRunResult) and not self.services.valid_upload_result(result):
            self._on_worker_error("YouTube chưa trả video ID hợp lệ; chưa thể báo thành công.")
            return
        self.progress_upload.setValue(100)
        self._update_upload_button_state()
        self._update_stepper_state()

        self.btn_cancel_upload.setVisible(False)
        self._active_upload_worker = None

        is_dry_run = isinstance(result, DryRunResult)
        if is_dry_run:
            self.state.set_dry_run_result(result)
            self._on_upload_result(result)
            ToastManager.instance().info("Chạy thử hoàn tất!", "Đã chạy thử quy trình thành công (không upload thật).")
            return

        is_scheduled = getattr(result, "status", None) == JobStatus.SCHEDULED

        self.state.set_upload_result(result)
        self._on_upload_result(result)

        if is_scheduled:
            local_time_str = self.dt_publish.dateTime().toString("dd/MM/yyyy HH:mm")
            ToastManager.instance().success(
                "Đã lên lịch thành công!",
                f"Đã lên lịch video thành công! Lịch công khai dự kiến là {local_time_str}."
            )
        else:
            ToastManager.instance().success("Tải lên thành công!", "Đăng video lên YouTube thành công!")

        # Save to history repository
        try:
            meta = self.state.meta
            download = self.state.download_result
            sel_acc = self.combo_channel.itemData(self.combo_channel.currentIndex()) if hasattr(self, "combo_channel") else None
            ch_id = getattr(result, "channel_id", "") or (sel_acc.id if sel_acc else "") or (self.services.connection.channel.id if self.services.connection.channel else "")
            job_status = JobStatus.SCHEDULED if is_scheduled else JobStatus.UPLOADED

            existing = next((r for r in self.services.history.list_scheduled()
                             if r.get("youtube_video_id") == result.video_id
                             and r.get("channel_id") == result.channel_id), None) if is_scheduled else None
            if existing is not None:
                details = {"original_title": meta.title if meta else self.state.title}
                if meta is not None:
                    details.update(tiktok_video_id=meta.video_id, tiktok_url=meta.url)
                if download is not None:
                    details.update(sha256=download.sha256, file_size=download.size)
                self.services.history.update(existing["id"], details)
                return
            self.services.history.add({
                "video_id": meta.video_id if meta else getattr(result, "video_id", ""),
                "url": meta.url if meta else "",
                "title": meta.title if meta else self.state.title,
                "youtube_title": self.state.title,
                "youtube_description": self.state.description,
                "youtube_video_id": getattr(result, "video_id", ""),
                "youtube_url": getattr(result, "url", ""),
                "youtube_channel_id": ch_id,
                "channel_id": ch_id,
                "local_mp4_path": str(self.state.local_video_path) if self.state.local_video_path else "",
                "sha256": download.sha256 if download else "",
                "status": job_status,
                "privacy_status": "private" if is_scheduled else self.state.privacy,
                "rights_confirmed": self.state.rights_confirmed,
                "publish_at": self.state.publish_at.isoformat() if self.state.publish_at else None,
                "scheduled_at": self.state.publish_at.isoformat() if self.state.publish_at else None,
            })
        except Exception:
            QMessageBox.warning(self, "Lịch sử", "Không lưu được lịch sử video. Hãy kiểm tra lại trước khi thử tải lên lần nữa.")

    @Slot()
    def _on_cancel_upload(self) -> None:
        if self._active_upload_worker:
            self._active_upload_worker.cancel()

    @Slot()
    def _on_upload_cancelled(self) -> None:
        self.services.connection.end_upload(self)
        self._update_upload_button_state()
        self._update_stepper_state()

        self.btn_cancel_upload.setVisible(False)
        self.progress_upload.setVisible(False)
        self._active_upload_worker = None
        self._notify("info", "Đã hủy", "Đã hủy quá trình tải lên YouTube.")

    @Slot(object)
    def _on_upload_result(self, result) -> None:
        simulated = isinstance(result, DryRunResult)
        visible = simulated or (result is not None and self.services.valid_upload_result(result))
        self.upload_result_box.setVisible(visible)
        if not visible:
            return

        is_scheduled = not simulated and (getattr(result, "status", None) == JobStatus.SCHEDULED)

        if simulated:
            self.lbl_upload_status.setText("Chạy thử hoàn tất, chưa đăng YouTube")
            self.lbl_upload_summary.setText(result.summary if hasattr(result, "summary") else "")
            self.lbl_upload_summary.setVisible(True)
            self.lbl_upload_url.setVisible(False)
            self.btn_open_youtube.setVisible(False)
            self.btn_copy_link.setVisible(False)
        elif is_scheduled:
            local_time_str = self.dt_publish.dateTime().toString("dd/MM/yyyy HH:mm")
            self.lbl_upload_status.setText(f"Đã lên lịch phát hành ({local_time_str})")
            self.lbl_upload_summary.setText(f"Video đã tải lên ở chế độ Riêng tư. Lịch công khai dự kiến là lúc {local_time_str} (giờ máy tính).")
            self.lbl_upload_summary.setVisible(True)
            self.lbl_upload_url.setText(f"Liên kết quản lý: {result.url}")
            self.lbl_upload_url.setVisible(True)
            self.btn_open_youtube.setVisible(True)
            self.btn_copy_link.setVisible(True)

        else:
            self.lbl_upload_status.setText("Đã tải video lên YouTube")
            self.lbl_upload_summary.setVisible(False)
            self.lbl_upload_url.setText(f"Liên kết: {result.url}")
            self.lbl_upload_url.setVisible(True)
            self.btn_open_youtube.setVisible(True)
            self.btn_copy_link.setVisible(True)

    @Slot()
    def _on_open_youtube_clicked(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            QDesktopServices.openUrl(QUrl(self.state.upload_result.url))

    @Slot()
    def _on_copy_link_clicked(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            QGuiApplication.clipboard().setText(self.state.upload_result.url)
            self._notify("info", "Đã sao chép", "Đã sao chép liên kết video YouTube.")

    # ---------------------------------------------------------
    # Common error & reset
    # ---------------------------------------------------------
    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self.services.connection.end_upload(self)
        if hasattr(self, "_ai_timer") and self._ai_timer.isActive():
            self._ai_timer.stop()
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.btn_generate_ai.setEnabled(True)
        self._update_upload_button_state()
        self._update_stepper_state()


        self.btn_cancel_upload.setVisible(False)
        self.progress_download.setVisible(False)
        self.progress_ai.setVisible(False)
        self.progress_upload.setVisible(False)
        self.state.error_message = message
        self._notify("error", "Lỗi tác vụ", f"Đã xảy ra lỗi: {message}")

    @Slot()
    def _on_reset_clicked(self) -> None:
        dialog = ConfirmDialog(
            title="Làm mới tác vụ",
            message="Bạn có chắc chắn muốn làm mới toàn bộ dữ liệu đang làm việc không?",
            confirm_text="Làm mới",
            cancel_text="Hủy",
            is_danger=True,
            icon_name="refresh",
            parent=self,
        )
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.state.reset()
            self.player_widget.clear()
            self.upload_result_box.setVisible(False)
            self.tiktok_meta_box.setVisible(False)
            self.progress_download.setVisible(False)
            self.progress_ai.setVisible(False)
            self.progress_upload.setVisible(False)


    @Slot(str, str)
    def _on_model_selected(self, model, message):
        self.services.settings.set('gemini_model', model)
        self.lbl_model_notice.setText(message)
