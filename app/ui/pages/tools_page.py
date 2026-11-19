"""Tools page: Responsive standalone utilities for TikTok downloading and AI generation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Slot, QEvent
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QGridLayout, QSizePolicy,
    QLabel, QLineEdit, QProgressBar,
    QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.ui import i18n as _i18n
from app.contracts import DownloadResult, GeneratedContent, VideoMeta
from app.core.paths import resolve_download_directory
from app.ui.model_loading import populate_models
from app.ui import tokens
from app.ui.components import AppButton, Card, ToastManager
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import DownloadVideoWorker, FetchMetaWorker, GenerateContentWorker


class ToolsPage(QWidget):
    """TikTok downloader and AI generator in one responsive workspace."""

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

        self._active_metadata_worker: Optional[FetchMetaWorker] = None
        self._download_destination: Optional[Path] = None
        self._active_download_worker: Optional[DownloadVideoWorker] = None
        self._active_ai_worker: Optional[GenerateContentWorker] = None

        self._init_ui()
        self.services.gemini_selection.changed.connect(self._on_model_selected)
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        heading = _i18n.ui(QLabel("Công cụ sáng tạo", container))
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(heading)
        hint = _i18n.ui(QLabel("Tải video TikTok và tạo nội dung AI ngay trên một trang.", container))
        hint.setProperty("class", "hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tools_grid = QGridLayout()
        self.tools_grid.setSpacing(16)
        self.download_card = self._create_download_card(container)
        self.ai_input_card = self._create_ai_input_card(container)
        self.ai_output_card = self._create_ai_output_card(container)
        for name, card in [("toolsDownload", self.download_card), ("toolsAIInput", self.ai_input_card), ("toolsAIOutput", self.ai_output_card)]:
            card.setObjectName(name)
            card.setStyleSheet(f"QFrame#{name} {{ padding: 0px; }}")
            card.main_layout.setContentsMargins(20, 18, 20, 18)
            card.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addLayout(self.tools_grid)
        layout.addStretch()
        self._layout_wide = None
        self._reflow_tools(0)
        self.scroll.setWidget(container)
        self.scroll.viewport().installEventFilter(self)
        outer.addWidget(self.scroll)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow_tools(event.size().width())
        return super().eventFilter(watched, event)

    def _reflow_tools(self, width: int) -> None:
        wide = width >= 1060
        if wide == self._layout_wide:
            return
        self._layout_wide = wide
        for card in (self.download_card, self.ai_input_card, self.ai_output_card):
            self.tools_grid.removeWidget(card)
        self.tools_grid.setColumnStretch(0, 1)
        self.tools_grid.setColumnStretch(1, 1 if wide else 0)
        self.tools_grid.addWidget(self.download_card, 0, 0)
        if wide:
            self.tools_grid.addWidget(self.ai_input_card, 0, 1)
            self.tools_grid.addWidget(self.ai_output_card, 1, 0, 1, 2)
        else:
            self.tools_grid.addWidget(self.ai_input_card, 1, 0)
            self.tools_grid.addWidget(self.ai_output_card, 2, 0)

    def _create_download_card(self, container: QWidget) -> Card:
        input_card = Card(title="Tải video TikTok", icon="download", parent=container)
        c_layout = QVBoxLayout()
        c_layout.setSpacing(12)

        # URL row 1
        row_url1 = QHBoxLayout()
        row_url1.setSpacing(8)
        self.input_url = QLineEdit(input_card)
        self.edit_url = self.input_url  # alias
        _i18n.placeholder(self.input_url, "Dán liên kết TikTok…")
        row_url1.addWidget(self.input_url, stretch=1)

        self.btn_paste = _i18n.ui(AppButton("Dán", variant="secondary", icon_name="paste", parent=input_card))
        self.btn_paste.clicked.connect(self._on_paste_tiktok)
        row_url1.addWidget(self.btn_paste)
        self.btn_download = _i18n.ui(AppButton("Tải về máy", variant="primary", icon_name="download", parent=input_card))
        self.btn_download.clicked.connect(self._on_download_tiktok)
        row_url1.addWidget(self.btn_download)
        c_layout.addLayout(row_url1)

        # Folder selection row
        row_folder = QHBoxLayout()
        row_folder.setSpacing(8)
        lbl_dir = _i18n.ui(QLabel("Thư mục lưu:", input_card))
        lbl_dir.setProperty("class", "fieldLabel")
        row_folder.addWidget(lbl_dir)

        saved_dir = self.services.settings.get("download_dir") if self.services.settings else None
        default_dir = resolve_download_directory(saved_dir)
        self.edit_download_dir = QLineEdit(input_card)
        self.edit_download_dir.setText(str(default_dir))
        row_folder.addWidget(self.edit_download_dir, stretch=1)

        self.btn_browse_folder = _i18n.ui(AppButton("Chọn thư mục...", variant="secondary", icon_name="browse", parent=input_card))
        self.btn_browse_folder.clicked.connect(self._on_browse_download_dir)
        row_folder_actions = QHBoxLayout()
        row_folder_actions.setSpacing(8)
        row_folder_actions.addWidget(self.btn_browse_folder)

        self.btn_open_folder = _i18n.ui(AppButton("Mở thư mục", variant="ghost", icon_name="link", parent=input_card))
        self.btn_open_folder.clicked.connect(self._on_open_download_folder)
        row_folder_actions.addWidget(self.btn_open_folder)
        row_folder_actions.addStretch()
        c_layout.addLayout(row_folder)
        c_layout.addLayout(row_folder_actions)
        rights = _i18n.ui(QLabel("Chỉ tải video bạn sở hữu hoặc được phép sử dụng.", input_card))
        rights.setWordWrap(True)
        rights.setProperty("class", "hintLabel")
        c_layout.addWidget(rights)

        # Progress bar
        row_prog = QHBoxLayout()
        self.progress_download = QProgressBar(input_card)
        self.progress_bar = self.progress_download  # alias
        self.progress_download.setRange(0, 100)
        self.progress_download.setValue(0)
        self.progress_download.setVisible(False)
        row_prog.addWidget(self.progress_download, stretch=1)

        self.btn_cancel_download = _i18n.ui(AppButton("Hủy", variant="danger", icon_name="cancel", parent=input_card))
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download)
        row_prog.addWidget(self.btn_cancel_download)
        c_layout.addLayout(row_prog)

        self.lbl_download_result = QLabel("", input_card)
        self.lbl_download_result.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_download_result.setWordWrap(True)
        self.lbl_download_result.setProperty("class", "hintLabel")
        self.lbl_download_result.hide()
        c_layout.addWidget(self.lbl_download_result)
        input_card.add_layout(c_layout)
        return input_card

    def _create_ai_input_card(self, container: QWidget) -> Card:
        in_card = Card(title="Tạo nội dung AI", icon="sparkle", parent=container)
        in_layout = QVBoxLayout()
        in_layout.setSpacing(10)

        # Pull from current job button
        row_top = QHBoxLayout()
        self.btn_pull_current = _i18n.ui(AppButton("Lấy từ tác vụ hiện tại", variant="ghost", icon_name="restore", parent=in_card))
        self.btn_pull_current.clicked.connect(self._on_pull_from_current_job)
        row_top.addWidget(self.btn_pull_current)
        row_top.addStretch()
        in_layout.addLayout(row_top)

        lbl_orig_title = _i18n.ui(QLabel("Tiêu đề TikTok gốc:", in_card))
        lbl_orig_title.setProperty("class", "fieldLabel")
        in_layout.addWidget(lbl_orig_title)

        self.edit_ai_orig_title = QLineEdit(in_card)
        _i18n.placeholder(self.edit_ai_orig_title, "Nhập hoặc dán tiêu đề video gốc...")
        in_layout.addWidget(self.edit_ai_orig_title)

        # Model and generate action
        row_cfg1 = QHBoxLayout()
        row_cfg1.setSpacing(12)

        lbl_model = _i18n.ui(QLabel("Mô hình AI:", in_card))
        lbl_model.setProperty("class", "fieldLabel")
        row_cfg1.addWidget(lbl_model)

        self.combo_model = QComboBox(in_card)
        self.combo_model.setMinimumContentsLength(10)
        self.combo_model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_model.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        populate_models(self.combo_model, self.services, notify=False)
        self.combo_model.currentIndexChanged.connect(self._on_model_combo_changed)
        row_cfg1.addWidget(self.combo_model, stretch=1)

        self.btn_generate_ai = _i18n.ui(AppButton("Tạo nội dung AI", variant="primary", icon_name="sparkle", parent=in_card))
        self.btn_generate_ai.clicked.connect(self._on_generate_ai_clicked)
        row_cfg1.addWidget(self.btn_generate_ai)
        in_layout.addLayout(row_cfg1)

        self.progress_ai = QProgressBar(in_card)
        self.progress_ai.setRange(0, 100)
        self.progress_ai.setValue(0)
        self.progress_ai.setVisible(False)
        in_layout.addWidget(self.progress_ai)

        in_card.add_layout(in_layout)
        return in_card

    def _create_ai_output_card(self, container: QWidget) -> Card:
        out_card = Card(title="Kết quả nội dung AI", parent=container)
        o_layout = QVBoxLayout()
        o_layout.setSpacing(12)

        # Title row
        title_head = QHBoxLayout()
        lbl_res_title = _i18n.ui(QLabel("Tiêu đề YouTube (tối đa 100 ký tự):", out_card))
        lbl_res_title.setProperty("class", "fieldLabel")
        title_head.addWidget(lbl_res_title)
        title_head.addStretch()

        self.lbl_title_counter = _i18n.ui(QLabel("0/100 ký tự", out_card))
        self.lbl_title_counter.setProperty("class", "charCounter")
        title_head.addWidget(self.lbl_title_counter)

        self.btn_copy_title = _i18n.ui(AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card))
        self.btn_copy_title.clicked.connect(lambda: self._copy_to_clip(self.edit_title.text(), "tiêu đề"))
        title_head.addWidget(self.btn_copy_title)
        o_layout.addLayout(title_head)

        self.edit_title = QLineEdit(out_card)
        _i18n.placeholder(self.edit_title, "Tiêu đề sinh bởi AI sẽ xuất hiện tại đây...")
        self.edit_title.textChanged.connect(self._update_title_counter)
        o_layout.addWidget(self.edit_title)

        # Description row
        desc_head = QHBoxLayout()
        lbl_res_desc = _i18n.ui(QLabel("Mô tả Video:", out_card))
        lbl_res_desc.setProperty("class", "fieldLabel")
        desc_head.addWidget(lbl_res_desc)
        desc_head.addStretch()

        self.btn_copy_desc = _i18n.ui(AppButton("Sao chép", variant="ghost", icon_name="copy", parent=out_card))
        self.btn_copy_desc.clicked.connect(lambda: self._copy_to_clip(self.edit_desc.toPlainText(), "mô tả"))
        desc_head.addWidget(self.btn_copy_desc)
        o_layout.addLayout(desc_head)

        self.edit_desc = QTextEdit(out_card)
        _i18n.placeholder(self.edit_desc, "Mô tả sinh bởi AI sẽ xuất hiện tại đây...")
        self.edit_desc.setMinimumHeight(160)
        o_layout.addWidget(self.edit_desc)

        out_card.add_layout(o_layout)
        return out_card

    def _connect_state(self) -> None:
        if self.state:
            self.state.job_changed.connect(self._on_state_changed)
            self.state.content_changed.connect(self._on_content_changed)

    def _on_state_changed(self) -> None:
        if self.state.url and not self.input_url.text():
            self.input_url.setText(self.state.url)
        if self.state.title and not self.edit_title.text():
            self.edit_title.setText(self.state.title)
        if self.state.description and not self.edit_desc.toPlainText():
            self.edit_desc.setPlainText(self.state.description)

    def _on_content_changed(self, content: GeneratedContent) -> None:
        if content:
            if content.title:
                self.edit_title.setText(content.title)
            if content.description:
                self.edit_desc.setPlainText(content.description)

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

        self.lbl_download_result.hide()

        # Fetch metadata then download
        self._download_destination = dest_dir
        worker_meta = FetchMetaWorker(self.services.tiktok, url)
        self._active_metadata_worker = worker_meta
        worker_meta.signals.finished.connect(self._on_download_metadata)
        worker_meta.signals.cancelled.connect(self._on_download_cancelled)
        worker_meta.signals.error.connect(self._on_tiktok_error)
        self.thread_pool.start(worker_meta)

    @Slot(object)
    def _on_download_metadata(self, meta: VideoMeta) -> None:
        self._active_metadata_worker = None
        if self._download_destination is not None:
            self._start_video_download(meta, self._download_destination)

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

        file_path = Path(result.path)
        _i18n.format_text(self.lbl_download_result, 'Đã tải: {0}', f'{file_path.name}')
        self.lbl_download_result.setToolTip(str(file_path))
        self.lbl_download_result.show()
        self._notify("success", "Tải hoàn tất", f"Video đã được tải về: {file_path.name}")

    @Slot()
    def _on_cancel_download(self) -> None:
        if self._active_metadata_worker:
            self._active_metadata_worker.cancel()
        if self._active_download_worker:
            self._active_download_worker.cancel()

    @Slot()
    def _on_download_cancelled(self) -> None:
        self._active_metadata_worker = None
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.progress_download.setVisible(False)
        self._active_download_worker = None
        self._notify("info", "Đã hủy", "Đã hủy thao tác tải video TikTok.")

    @Slot(str)
    def _on_tiktok_error(self, err: str) -> None:
        self._active_metadata_worker = None
        self.btn_download.setEnabled(True)
        self.btn_cancel_download.setVisible(False)
        self.progress_download.setVisible(False)
        self._active_download_worker = None
        self._notify("error", "Lỗi tải video", err)

    # =========================================================================
    # LOGIC & SLOTS: AI GENERATOR
    # =========================================================================
    @Slot()
    def _on_pull_from_current_job(self) -> None:
        if self.state.meta:
            self.edit_ai_orig_title.setText(self.state.meta.title or "")
            self._notify("info", "Đã lấy thông tin", "Đã điền tiêu đề từ tác vụ hiện tại.")
        elif self.state.title:
            self.edit_ai_orig_title.setText(self.state.title)
            self._notify("info", "Đã lấy thông tin", "Đã điền tiêu đề từ tác vụ hiện tại.")
        else:
            self._notify("warning", "Chưa có dữ liệu", "Tác vụ hiện tại chưa có thông tin video nào.")

    @Slot()
    def _on_generate_ai_clicked(self) -> None:
        orig_title = self.edit_ai_orig_title.text().strip()
        if not orig_title:
            self._notify("warning", "Thiếu thông tin", "Vui lòng nhập tiêu đề gốc.")
            return

        self.btn_generate_ai.setEnabled(False)
        self.progress_ai.setVisible(True)
        self.progress_ai.setValue(20)

        meta = VideoMeta(
            video_id="standalone-ai",
            url="",
            title=orig_title or "Video TikTok",
            description="",
            author="User",
            thumbnail_url=None,
            duration=60.0,
            width=1080,
            height=1920,
        )

        settings = {
            "model": self.combo_model.currentData() or self.combo_model.currentText(),
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

        self._notify("success", "Tạo nội dung thành công", "AI đã tạo xong tiêu đề và mô tả.")

    @Slot(str)
    def _on_ai_error(self, err: str) -> None:
        self.btn_generate_ai.setEnabled(True)
        self.progress_ai.setVisible(False)
        self._active_ai_worker = None
        self._notify("error", "Lỗi sinh nội dung AI", err)

    def _update_title_counter(self, text: str) -> None:
        count = len(text)
        _i18n.format_text(self.lbl_title_counter, '{0}/100 ký tự', f'{count}')
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

    def _on_model_combo_changed(self, idx: int) -> None:
        model = self.combo_model.itemData(idx)
        if model and self.services.settings:
            self.services.settings.set("gemini_model", model)

    @Slot(str, str)
    def _on_model_selected(self, model: str, message: str) -> None:
        if self.services.settings:
            self.services.settings.set("gemini_model", model)
        self.combo_model.blockSignals(True)
        idx = self.combo_model.findData(model)
        if idx < 0:
            self.combo_model.addItem(model, model)
            idx = self.combo_model.count() - 1
        self.combo_model.setCurrentIndex(idx)
        self.combo_model.blockSignals(False)
