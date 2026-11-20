"""Settings and configuration page with General, Gemini, YouTube, Storage, and yt-dlp update."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Slot, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from app.ui import i18n as _i18n
from app.core.paths import project_root, resolve_download_directory
from app.ui.model_loading import populate_models
from app.ui import branding, tokens
from app.ui.components import AppButton, Card, ConfirmDialog
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import YtDlpUpdateWorker


class SettingsPage(QWidget):
    """Application configuration and credentials management."""

    appearance_changed = Signal()

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
        self._active_ytdlp_worker: Optional[YtDlpUpdateWorker] = None

        self._init_ui()
        self._load_settings()
        self.services.gemini_selection.changed.connect(self._on_model_selected)
        self.services.add_mode_banner(self)
        self.services.connection.changed.connect(self._show_channel)
        self.services.connection.error.connect(self._connection_error)
        self._show_channel()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header
        header = _i18n.ui(QLabel("Cài Đặt Hệ Thống", container))
        header.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        layout.addWidget(header)

        sub = _i18n.formatted(QLabel(
            '',
            container,
        ), 'Quản lý toàn diện cấu hình ứng dụng {0} (phiên bản v{1}): Tùy chọn chung, Gemini AI, YouTube OAuth, Lưu trữ & Dọn dẹp cache.', f'{branding.APP_NAME}', f'{branding.APP_VERSION}')
        sub.setProperty("class", "hintLabel")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # =============================================================
        # 1. GENERAL SETTINGS CARD
        # =============================================================
        gen_card = Card(title="1. Cài đặt chung (General)", parent=container)
        g_layout = QGridLayout()
        g_layout.setSpacing(12)

        # Ngôn ngữ UI
        lbl_lang = _i18n.ui(QLabel("Ngôn ngữ giao diện:", gen_card))
        lbl_lang.setProperty("class", "fieldLabel")
        g_layout.addWidget(lbl_lang, 0, 0)

        self.combo_lang = QComboBox(gen_card)
        self.combo_lang.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_lang.setMinimumWidth(80)
        _i18n.add_item(self.combo_lang, "Tiếng Việt (Mặc định)", "vi")
        self.combo_lang.addItem("English", "en")
        self.combo_lang.currentIndexChanged.connect(
            self._appearance_changed
        )
        g_layout.addWidget(self.combo_lang, 1, 0)

        # Giao diện (Theme)
        lbl_theme = _i18n.ui(QLabel("Chế độ hiển thị (Theme):", gen_card))
        lbl_theme.setProperty("class", "fieldLabel")
        g_layout.addWidget(lbl_theme, 0, 1)

        self.combo_theme = QComboBox(gen_card)
        self.combo_theme.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_theme.setMinimumWidth(80)
        _i18n.add_item(self.combo_theme, "Dark Mode (Tối chuyên nghiệp - Mặc định)", "dark")
        _i18n.add_item(self.combo_theme, "Light Mode (Sáng)", "light")
        self.combo_theme.currentIndexChanged.connect(
            self._appearance_changed
        )
        g_layout.addWidget(self.combo_theme, 1, 1)

        # Thư mục tải về
        lbl_dir = _i18n.ui(QLabel("Thư mục lưu video tải về:", gen_card))
        lbl_dir.setProperty("class", "fieldLabel")
        g_layout.addWidget(lbl_dir, 2, 0, 1, 2)

        dir_box = QHBoxLayout()
        self.edit_download_dir = QLineEdit(gen_card)
        initial_dir = resolve_download_directory(
            self.services.settings.get("download_dir") if self.services.settings else None
        )
        self.edit_download_dir.setText(str(initial_dir))
        dir_box.addWidget(self.edit_download_dir, stretch=1)

        self.btn_browse_dir = _i18n.ui(AppButton("Chọn thư mục...", variant="secondary", icon_name="folder-open", parent=gen_card))
        self.btn_browse_dir.clicked.connect(self._browse_dir)
        dir_box.addWidget(self.btn_browse_dir)
        g_layout.addLayout(dir_box, 3, 0, 1, 2)

        # Privacy mặc định
        lbl_def_priv = _i18n.ui(QLabel("Chế độ hiển thị mặc định cho YouTube:", gen_card))
        lbl_def_priv.setProperty("class", "fieldLabel")
        g_layout.addWidget(lbl_def_priv, 4, 0)

        self.combo_def_privacy = QComboBox(gen_card)
        self.combo_def_privacy.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_def_privacy.setMinimumWidth(80)
        _i18n.add_item(self.combo_def_privacy, "Riêng tư (Private) - Khuyên dùng an toàn", "private")
        _i18n.add_item(self.combo_def_privacy, "Không công khai (Unlisted)", "unlisted")
        _i18n.add_item(self.combo_def_privacy, "Công khai (Public)", "public")
        self.combo_def_privacy.currentIndexChanged.connect(self._on_def_privacy_changed)
        g_layout.addWidget(self.combo_def_privacy, 5, 0)

        # Đối tượng xem mặc định
        lbl_def_kids = _i18n.ui(QLabel("Đối tượng người xem mặc định:", gen_card))
        lbl_def_kids.setProperty("class", "fieldLabel")
        g_layout.addWidget(lbl_def_kids, 4, 1)

        self.combo_def_made_for_kids = QComboBox(gen_card)
        self.combo_def_made_for_kids.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_def_made_for_kids.setMinimumWidth(80)
        _i18n.add_item(self.combo_def_made_for_kids, "Không chọn trước (Bắt buộc chọn mỗi lần)", "")
        _i18n.add_item(self.combo_def_made_for_kids, "Không, không dành cho trẻ em (Khuyên dùng)", "no")
        _i18n.add_item(self.combo_def_made_for_kids, "Có, dành cho trẻ em", "yes")
        self.combo_def_made_for_kids.currentIndexChanged.connect(self._on_def_kids_changed)
        g_layout.addWidget(self.combo_def_made_for_kids, 5, 1)

        gen_card.add_layout(g_layout)
        layout.addWidget(gen_card)

        # =============================================================
        # 2. GEMINI AI SETTINGS CARD
        # =============================================================
        api_card = Card(title="2. Trí tuệ nhân tạo (Google Gemini AI)", parent=container)
        api_layout = QGridLayout()
        api_layout.setSpacing(12)

        lbl_api = _i18n.ui(QLabel("Khóa bí mật Gemini API Key (ẩn an toàn):", api_card))
        lbl_api.setProperty("class", "fieldLabel")
        api_layout.addWidget(lbl_api, 0, 0, 1, 3)

        api_input_row = QHBoxLayout()
        self.edit_api_key = QLineEdit(api_card)
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        _i18n.placeholder(self.edit_api_key, "Nhập khóa API (lưu trữ mã hóa qua SecretStore)...")
        api_input_row.addWidget(self.edit_api_key, stretch=1)

        self.btn_toggle_key = _i18n.ui(AppButton("Hiện", variant="secondary", icon_name="eye", parent=api_card))
        self.btn_toggle_key.setFixedWidth(80)
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        api_input_row.addWidget(self.btn_toggle_key)

        self.btn_save_key = _i18n.ui(AppButton("Lưu khóa", variant="primary", icon_name="content-save", parent=api_card))
        self.btn_save_key.clicked.connect(self._save_api_key)
        api_input_row.addWidget(self.btn_save_key)

        self.btn_test_gemini = _i18n.ui(AppButton("Kiểm tra kết nối", variant="secondary", icon_name="check-circle", parent=api_card))
        self.btn_test_gemini.clicked.connect(self._test_gemini)
        api_input_row.addWidget(self.btn_test_gemini)

        api_layout.addLayout(api_input_row, 1, 0, 1, 3)

        # Model selection
        lbl_model = _i18n.ui(QLabel("Mô hình AI:", api_card))
        lbl_model.setProperty("class", "fieldLabel")
        api_layout.addWidget(lbl_model, 2, 0)

        self.combo_gemini_model = QComboBox(api_card)
        self._populate_gemini_models()
        self.combo_gemini_model.currentIndexChanged.connect(
            lambda: self.services.settings.set("gemini_model", self.combo_gemini_model.currentData())
        )
        model_box = QVBoxLayout()
        model_row = QHBoxLayout()
        model_row.addWidget(self.combo_gemini_model, 1)
        self.btn_default_model = _i18n.ui(AppButton('Đặt làm mặc định', variant='secondary', icon_name='check', parent=api_card))
        self.btn_default_model.clicked.connect(self._set_default_model)
        model_row.addWidget(self.btn_default_model)
        model_box.addLayout(model_row)
        self.lbl_default_model = QLabel(api_card)
        self.lbl_default_model.setWordWrap(True)
        self.lbl_default_model.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_default_model.setProperty('class', 'hintLabel')
        model_box.addWidget(self.lbl_default_model)
        self._refresh_default_model_hint()
        api_layout.addLayout(model_box, 2, 1, 1, 2)

        # Files API video analysis flag
        chk_box = QVBoxLayout()
        chk_box.setSpacing(2)
        self.chk_analyze_video = _i18n.ui(QCheckBox("Phân tích nội dung MP4 bằng Gemini (Files API)", api_card))
        self.chk_analyze_video.toggled.connect(self._on_analyze_video_toggled)
        chk_box.addWidget(self.chk_analyze_video)

        lbl_chk_hint = _i18n.ui(QLabel("Tắt: dùng tiêu đề và mô tả gốc. Bật: gửi MP4 lên Google để AI phân tích video; có thể tốn thêm thời gian và hạn mức.", api_card))
        lbl_chk_hint.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED}; margin-left: 26px;")
        lbl_chk_hint.setWordWrap(True)
        chk_box.addWidget(lbl_chk_hint)
        api_layout.addLayout(chk_box, 3, 0, 1, 3)

        # Custom Prompt Template
        lbl_prompt = _i18n.ui(QLabel("Hướng dẫn AI viết tiêu đề và mô tả (tùy chọn):", api_card))
        lbl_prompt.setProperty("class", "fieldLabel")
        api_layout.addWidget(lbl_prompt, 4, 0, 1, 3)

        self.edit_prompt = QTextEdit(api_card)
        _i18n.placeholder(self.edit_prompt, "Ví dụ: Viết tiêu đề ngắn gọn và mô tả bằng tiếng Việt cho video {title}. Nội dung gốc: {description}.")
        self.edit_prompt.setMaximumHeight(85)
        self.edit_prompt.textChanged.connect(self._on_prompt_changed)
        api_layout.addWidget(self.edit_prompt, 5, 0, 1, 3)
        prompt_hint = _i18n.ui(QLabel('Để trống để dùng mẫu có sẵn. Dùng {title} và {description} để đưa tiêu đề, mô tả gốc vào hướng dẫn. Đây không phải lệnh tự động tải/đăng video.', api_card))
        prompt_hint.setWordWrap(True)
        prompt_hint.setProperty('class', 'hintLabel')
        api_layout.addWidget(prompt_hint, 6, 0, 1, 3)

        api_card.add_layout(api_layout)
        layout.addWidget(api_card)

        # =============================================================
        # 3. YOUTUBE OAUTH & CHANNEL CARD
        # =============================================================
        yt_card = Card(title="3. Cấu hình YouTube OAuth", parent=container)
        yt_layout = QVBoxLayout()
        yt_layout.setSpacing(12)
        from app.services.youtube.auth import OAUTH_SCOPE_EXPLANATION
        scope_notice = QLabel(OAUTH_SCOPE_EXPLANATION, yt_card)
        scope_notice.setWordWrap(True)
        yt_layout.addWidget(scope_notice)

        # client_secret.json picker
        lbl_secret = _i18n.ui(QLabel("Tệp cấu hình YouTube OAuth (client_secret.json):", yt_card))
        lbl_secret.setProperty("class", "fieldLabel")
        yt_layout.addWidget(lbl_secret)

        secret_row = QHBoxLayout()
        self.edit_client_secret = QLineEdit(yt_card)
        _i18n.placeholder(self.edit_client_secret, "Đường dẫn tệp client_secret.json...")
        secret_row.addWidget(self.edit_client_secret, stretch=1)

        self.btn_browse_secret = _i18n.ui(AppButton("Chọn file JSON...", variant="secondary", icon_name="folder-open", parent=yt_card))
        self.btn_browse_secret.clicked.connect(self._browse_client_secret)
        secret_row.addWidget(self.btn_browse_secret)
        yt_layout.addLayout(secret_row)

        # Notice guiding user to YouTube Channels page
        note_box = QFrame(yt_card)
        note_box.setObjectName("ytNoteBox")
        note_box.setStyleSheet(
            f"QFrame#ytNoteBox {{ background-color: {tokens.BG_CARD_HOVER}; border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_MD}px; padding: 12px; }}"
            f"QFrame#ytNoteBox QLabel {{ border: none; background: transparent; }}"
        )
        note_layout = QHBoxLayout(note_box)
        note_layout.setSpacing(12)

        from app.ui.icons import get_icon
        lbl_note_icon = QLabel(note_box)
        lbl_note_icon.setPixmap(get_icon("info", color=tokens.COLOR_PRIMARY).pixmap(24, 24))
        note_layout.addWidget(lbl_note_icon)

        lbl_note_text = _i18n.ui(QLabel(
            "Để kết nối, thêm tài khoản mới, đổi kênh mặc định hoặc xem thống kê chi tiết các kênh, "
            "vui lòng sử dụng mục <b>Kênh YouTube</b> trên thanh điều hướng.",
            note_box,
        ))
        lbl_note_text.setWordWrap(True)
        lbl_note_text.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 13px;")
        note_layout.addWidget(lbl_note_text, stretch=1)

        yt_layout.addWidget(note_box)
        yt_card.add_layout(yt_layout)
        layout.addWidget(yt_card)

        # Compatibility attributes (kept for test/API compatibility but hidden from UI)
        self.lbl_yt_channel_name = QLabel(self)
        self.lbl_yt_channel_name.setVisible(False)
        self.lbl_yt_channel_id = QLabel(self)
        self.lbl_yt_channel_id.setVisible(False)
        self.btn_connect_yt = _i18n.ui(AppButton("Kết nối kênh", parent=self))
        self.btn_connect_yt.setVisible(False)
        self.btn_connect_yt.clicked.connect(self._connect_youtube)
        self.btn_disconnect_yt = _i18n.ui(AppButton("Ngắt kết nối", parent=self))
        self.btn_disconnect_yt.setVisible(False)
        self.btn_disconnect_yt.clicked.connect(self._disconnect_youtube)

        # =============================================================
        # 4. STORAGE & CACHE CARD
        # =============================================================
        storage_card = Card(title="4. Quản lý lưu trữ & Bộ nhớ đệm (Storage)", parent=container)
        st_layout = QGridLayout()
        st_layout.setSpacing(12)

        # DB location
        lbl_db = _i18n.ui(QLabel("Vị trí cơ sở dữ liệu SQLite:", storage_card))
        lbl_db.setProperty("class", "fieldLabel")
        st_layout.addWidget(lbl_db, 0, 0)

        db_path = getattr(self.services.history, "path", None) or (project_root() / "data" / "app.db")
        self.lbl_db_path = QLabel(str(db_path))
        self.lbl_db_path.setStyleSheet("color: #cbd5e1; font-family: monospace;")
        st_layout.addWidget(self.lbl_db_path, 1, 0)

        # Logs location
        lbl_log = _i18n.ui(QLabel("Thư mục nhật ký (Logs):", storage_card))
        lbl_log.setProperty("class", "fieldLabel")
        st_layout.addWidget(lbl_log, 0, 1)

        btn_open_logs = _i18n.ui(AppButton("Mở thư mục Logs", variant="secondary", icon_name="folder-open", parent=storage_card))
        btn_open_logs.clicked.connect(self._open_logs_dir)
        st_layout.addWidget(btn_open_logs, 1, 1)

        # Clear Cache button
        self.btn_clear_cache = _i18n.ui(AppButton("Xóa bộ nhớ đệm (Clear Cache)...", variant="danger", icon_name="trash-can", parent=storage_card))
        self.btn_clear_cache.clicked.connect(self._clear_cache_with_confirm)
        st_layout.addWidget(self.btn_clear_cache, 2, 0, 1, 2)

        storage_card.add_layout(st_layout)
        layout.addWidget(storage_card)

        # =============================================================
        # 5. YT-DLP UPDATE CARD
        # =============================================================
        ytdlp_card = Card(title="5. Công cụ tải video (yt-dlp)", parent=container)
        y_layout = QVBoxLayout()
        y_layout.setSpacing(10)

        y_row = QHBoxLayout()
        self.lbl_ytdlp_version = _i18n.ui(QLabel("Phiên bản hiện tại: 2026.10.26", ytdlp_card))
        self.lbl_ytdlp_version.setStyleSheet("font-weight: 600; color: #f8fafc;")
        y_row.addWidget(self.lbl_ytdlp_version, stretch=1)

        self.btn_update_ytdlp = _i18n.ui(AppButton("Kiểm tra & Cập nhật yt-dlp", variant="secondary", icon_name="refresh", parent=ytdlp_card))
        self.btn_update_ytdlp.clicked.connect(self._update_ytdlp)
        y_row.addWidget(self.btn_update_ytdlp)
        y_layout.addLayout(y_row)

        self.progress_ytdlp = QProgressBar(ytdlp_card)
        self.progress_ytdlp.setRange(0, 100)
        self.progress_ytdlp.setValue(0)
        self.progress_ytdlp.setVisible(False)
        y_layout.addWidget(self.progress_ytdlp)

        self.lbl_ytdlp_result = QLabel("")
        self.lbl_ytdlp_result.setProperty("class", "hintLabel")
        y_layout.addWidget(self.lbl_ytdlp_result)

        ytdlp_card.add_layout(y_layout)
        layout.addWidget(ytdlp_card)

        # =============================================================
        # 6. ABOUT APPLICATION CARD
        # =============================================================
        about_card = Card(title=f"6. Thông tin ứng dụng ({branding.APP_NAME})", parent=container)
        about_layout = QHBoxLayout()
        about_layout.setSpacing(16)

        lbl_about_icon = QLabel(about_card)
        lbl_about_icon.setPixmap(branding.get_logo_pixmap(48))
        lbl_about_icon.setFixedSize(48, 48)
        about_layout.addWidget(lbl_about_icon)

        about_text_box = QVBoxLayout()
        about_text_box.setSpacing(4)
        lbl_about_title = _i18n.formatted(QLabel('', about_card), '{0} — Phiên bản v{1}', f'{branding.APP_NAME}', f'{branding.APP_VERSION}')
        lbl_about_title.setStyleSheet("font-weight: 700; font-size: 14px; color: #ffffff;")
        about_text_box.addWidget(lbl_about_title)

        lbl_about_desc = QLabel(branding.APP_DESCRIPTION, about_card)
        lbl_about_desc.setProperty("class", "hintLabel")
        lbl_about_desc.setWordWrap(True)
        about_text_box.addWidget(lbl_about_desc)
        about_layout.addLayout(about_text_box, stretch=1)

        about_card.add_layout(about_layout)
        layout.addWidget(about_card)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _populate_gemini_models(self) -> None:
        populate_models(self.combo_gemini_model, self.services)

    def _appearance_changed(self) -> None:
        self.services.settings.set('ui_language', self.combo_lang.currentData())
        self.services.settings.set('ui_theme', self.combo_theme.currentData())
        self.appearance_changed.emit()

    def _load_settings(self) -> None:
        for combo, key, default in (
            (self.combo_lang, 'ui_language', 'vi'),
            (self.combo_theme, 'ui_theme', 'dark'),
        ):
            previous = combo.blockSignals(True)
            index = combo.findData(self.services.settings.get(key, default))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(previous)
        # Load API key
        key = self.services.secrets.get("gemini_api_key")
        if key:
            self.edit_api_key.setText(key)

        # Client contents are in SecretStore, not a reusable filesystem path.
        _i18n.placeholder(self.edit_client_secret, 'Chỉ chọn JSON lần đầu hoặc khi đổi project; client đã lưu sẽ được dùng lại.')

        # Load flags
        analyze_flag = bool(self.services.settings.get("analyze_video_file", False))
        self.chk_analyze_video.setChecked(analyze_flag)

        custom_prompt = self.services.settings.get("gemini_prompt_template", "")
        if custom_prompt:
            self.edit_prompt.setPlainText(custom_prompt)

        # Safe startup default; old persisted Public must not publish new jobs.
        def_priv = 'private'
        self.services.settings.set('default_privacy', def_priv)
        idx = self.combo_def_privacy.findData(def_priv)
        if idx >= 0:
            self.combo_def_privacy.setCurrentIndex(idx)

        # Load default made for kids
        saved_kids = self.services.settings.get("default_made_for_kids", "") if self.services.settings else ""
        idx_kids = self.combo_def_made_for_kids.findData(saved_kids)
        if idx_kids >= 0:
            self.combo_def_made_for_kids.blockSignals(True)
            self.combo_def_made_for_kids.setCurrentIndex(idx_kids)
            self.combo_def_made_for_kids.blockSignals(False)

        # Load download directory
        saved_dir = self.services.settings.get("download_dir") if self.services.settings else None
        resolved_dir = resolve_download_directory(saved_dir)
        self.edit_download_dir.setText(str(resolved_dir))
        if self.services.settings:
            self.services.settings.set("download_dir", str(resolved_dir))

        # Detect yt-dlp version
        try:
            import yt_dlp
            ver = getattr(getattr(yt_dlp, "version", None), "__version__", "2026.10.26")
            _i18n.format_text(self.lbl_ytdlp_version, 'Phiên bản hiện tại: {0}', f'{ver}')
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Safe Path Checking with Warning per Requirement
    # -----------------------------------------------------------------
    def _check_and_confirm_outside_project_path(self, chosen_path: Path) -> bool:
        """Alert and require explicit user confirmation if selected path is outside project root."""
        root = project_root().resolve()
        chosen = chosen_path.resolve()
        try:
            is_inside = chosen.is_relative_to(root)
        except Exception:
            is_inside = False

        if not is_inside:
            reply = QMessageBox.warning(
                self,
                "⚠️ Cảnh báo đường dẫn ngoài dự án",
                f"Đường dẫn đã chọn nằm NGOÀI thư mục gốc của dự án:\n\n{chosen}\n\n"
                f"Theo quy tắc làm việc (AGENTS.md), toàn bộ dữ liệu, cache và công cụ "
                f"được khuyến nghị lưu trữ bên trong thư mục dự án ({root}).\n\n"
                f"Bạn có chắc chắn muốn sử dụng đường dẫn bên ngoài này không?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return reply == QMessageBox.StandardButton.Yes
        return True

    @Slot()
    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục tải về", self.edit_download_dir.text()
        )
        if d:
            p = Path(d)
            if self._check_and_confirm_outside_project_path(p):
                resolved = resolve_download_directory(p)
                self.edit_download_dir.setText(str(resolved))
                if self.services.settings:
                    self.services.settings.set("download_dir", str(resolved))

    @Slot()
    def _browse_client_secret(self) -> None:
        from app.errors import AppError
        from app.services.youtube.auth import import_client_secret
        selected, _ = QFileDialog.getOpenFileName(self, "Chọn client_secret.json OAuth Desktop", "", "JSON Files (*.json)")
        if not selected:
            return
        try:
            path = Path(selected)
            if self.services.is_fake:
                import_client_secret(path, self.services.secrets)
            else:
                self.services.youtube.import_client_secret(path)
            self.services.connection.clear()
            _i18n.set_text(self.edit_client_secret, "Đã nhập OAuth Desktop client vào SecretStore")
        except Exception as error:
            self._connection_error(error.user_message if isinstance(error, AppError) else "Không đọc được OAuth Desktop client. Hãy chọn JSON loại Desktop hợp lệ.")

    @Slot()
    def _toggle_key_visibility(self) -> None:
        if self.edit_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            _i18n.set_text(self.btn_toggle_key, "Ẩn")
            self.btn_toggle_key.set_icon_name("eye-off")
        else:
            self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            _i18n.set_text(self.btn_toggle_key, "Hiện")
            self.btn_toggle_key.set_icon_name("eye")

    @Slot()
    def _save_api_key(self) -> None:
        k = self.edit_api_key.text().strip()
        if k:
            self.services.secrets.set("gemini_api_key", k)
            QMessageBox.information(self, "Đã lưu", "Đã lưu khóa API an toàn vào SecretStore.")
        else:
            self.services.secrets.delete("gemini_api_key")
            QMessageBox.information(self, "Đã xóa", "Đã xóa khóa bí mật khỏi SecretStore.")

    @Slot()
    def _test_gemini(self) -> None:
        try:
            ok = self.services.generator.test_connection()
            if ok:
                self._populate_gemini_models()
                QMessageBox.information(
                    self,
                    "Kết nối thành công",
                    "Kiểm tra kết nối Gemini AI thành công! Danh sách mô hình đã được làm mới.",
                )
            else:
                QMessageBox.warning(self, "Không phản hồi", "Dịch vụ Gemini AI không phản hồi.")
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi kết nối", f"Không thể kết nối: {exc}")

    def _refresh_default_model_hint(self):
        model = self.services.settings.get('gemini_default_model')
        _i18n.format_text(self.lbl_default_model,
            'Mặc định: {0} · Dùng khi mở ứng dụng.' if model else
            'Chưa đặt mặc định riêng. Chọn mô hình rồi bấm Đặt làm mặc định.', model)

    @Slot()
    def _set_default_model(self):
        model = self.combo_gemini_model.currentData()
        if not self.combo_gemini_model.isEnabled() or not isinstance(model, str) or not model:
            return
        self.services.settings.set('gemini_default_model', model)
        self.services.settings.set('gemini_model', model)
        self._refresh_default_model_hint()
        self.services.gemini_selection.changed.emit(model, 'Đã áp dụng mô hình mặc định: ' + model)

    @Slot(bool)
    def _on_analyze_video_toggled(self, checked: bool) -> None:
        self.services.settings.set("analyze_video_file", checked)

    @Slot()
    def _on_prompt_changed(self) -> None:
        text = self.edit_prompt.toPlainText().strip()
        self.services.settings.set("gemini_prompt_template", text)

    @Slot(int)
    def _on_def_privacy_changed(self, idx: int) -> None:
        val = self.combo_def_privacy.itemData(idx)
        if val:
            self.services.settings.set("default_privacy", val)
            self.state.privacy = val

    @Slot(int)
    def _on_def_kids_changed(self, idx: int) -> None:
        val = self.combo_def_made_for_kids.itemData(idx)
        if self.services.settings:
            self.services.settings.set("default_made_for_kids", val or "")

    def _show_channel(self) -> None:
        connection = self.services.connection
        channel = connection.channel
        self.lbl_yt_channel_name.setText(f"Kênh YouTube: {channel.title}" if channel else "Kênh YouTube: Chưa kết nối")
        self.lbl_yt_channel_id.setText(f"ID kênh: {channel.id} | Trạng thái: Đã kết nối" if channel else "ID kênh: - | Trạng thái: Chưa kết nối")
        self.btn_connect_yt.setEnabled(not connection.busy)
        self.btn_disconnect_yt.setEnabled(not connection.busy)
        self.btn_browse_secret.setEnabled(not connection.busy)

    def _connection_error(self, message: str) -> None:
        self.lbl_yt_channel_id.setText(message)

    @Slot()
    def _connect_youtube(self) -> None:
        self.services.connection.connect_service(self.services.youtube)

    @Slot()
    def _disconnect_youtube(self) -> None:
        if self.services.connection.busy:
            return
        self.services.connection.clear()
        try:
            self.services.youtube.disconnect()
        except Exception:
            self._connection_error("Không xóa được token trong SecretStore. Hãy thử ngắt kết nối lại.")

    @Slot()
    def _open_logs_dir(self) -> None:
        logs_dir = project_root() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir.resolve())))

    @Slot()
    def _clear_cache_with_confirm(self) -> None:
        dialog = ConfirmDialog(
            title="Xác nhận xóa bộ nhớ đệm (Clear Cache)",
            message="Thao tác này sẽ xóa toàn bộ các tệp tạm trong thư mục .tmp/\nBạn có chắc chắn muốn xóa bộ nhớ đệm không?",
            confirm_text="Xóa bộ nhớ đệm",
            cancel_text="Hủy",
            is_danger=True,
            icon_name="trash-can",
            parent=self,
        )
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            tmp_dir = project_root() / ".tmp"
            if tmp_dir.exists():
                count = 0
                for item in tmp_dir.iterdir():
                    if item.name == ".gitkeep":
                        continue
                    try:
                        if item.is_file():
                            item.unlink()
                            count += 1
                        elif item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                            count += 1
                    except Exception:
                        pass
                QMessageBox.information(
                    self, "Hoàn tất", f"Đã dọn dẹp {count} mục trong bộ nhớ đệm tạm thời."
                )

    @Slot()
    def _update_ytdlp(self) -> None:
        self.btn_update_ytdlp.setEnabled(False)
        self.progress_ytdlp.setVisible(True)
        self.progress_ytdlp.setValue(10)
        _i18n.set_text(self.lbl_ytdlp_result, "Đang kiểm tra phiên bản mới nhất...")

        worker = YtDlpUpdateWorker()
        self._active_ytdlp_worker = worker
        worker.signals.progress.connect(lambda p: self.progress_ytdlp.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_ytdlp_finished)
        worker.signals.error.connect(self._on_ytdlp_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_ytdlp_finished(self, msg: str) -> None:
        self.progress_ytdlp.setValue(100)
        self.btn_update_ytdlp.setEnabled(True)
        self.progress_ytdlp.setVisible(False)
        self.lbl_ytdlp_result.setText(str(msg))
        QMessageBox.information(self, "Cập nhật yt-dlp", str(msg))

    @Slot(str)
    def _on_ytdlp_error(self, err: str) -> None:
        self.btn_update_ytdlp.setEnabled(True)
        self.progress_ytdlp.setVisible(False)
        _i18n.format_text(self.lbl_ytdlp_result, 'Lỗi: {0}', f'{err}')
        QMessageBox.critical(self, "Lỗi cập nhật yt-dlp", str(err))

    @Slot(str, str)
    def _on_model_selected(self, model, message):
        self._refresh_default_model_hint()
        self.combo_gemini_model.blockSignals(True)
        index = self.combo_gemini_model.findData(model)
        if index < 0:
            self.combo_gemini_model.addItem(model, model)
            index = self.combo_gemini_model.count() - 1
        self.combo_gemini_model.setCurrentIndex(index)
        self.combo_gemini_model.blockSignals(False)
