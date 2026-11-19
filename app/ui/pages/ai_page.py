"""AI Content Generator dedicated page."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThreadPool, QTimer, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.ui import i18n as _i18n
from app.contracts import GeneratedContent
from app.services.gemini import select_preferred_model
from app.ui.components import AppButton, Card
from app.ui.services import ServiceContainer
from app.ui.state import JobState, format_hashtags
from app.workers import GenerateContentWorker


class AIPage(QWidget):
    """Dedicated AI Content generation workspace."""

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

        self._init_ui()
        self.lbl_model_notice = QLabel(self)
        self.lbl_model_notice.setWordWrap(True)
        self.lbl_model_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.layout().insertWidget(0, self.lbl_model_notice)
        self.services.gemini_selection.changed.connect(self._on_model_selected)
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
        header = _i18n.ui(QLabel("Tạo Nội Dung Bằng Trí Tuệ Nhân Tạo (Gemini)", container))
        header.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        layout.addWidget(header)

        sub = _i18n.ui(QLabel(
            "Tự động viết lại tiêu đề hấp dẫn, mô tả chuẩn SEO, tạo hashtag và thẻ gắn cho YouTube.",
            container,
        ))
        sub.setProperty("class", "hintLabel")
        layout.addWidget(sub)

        # Settings Card
        settings_card = Card(title="Cấu hình sinh nội dung", parent=container)
        s_layout = QGridLayout()
        s_layout.setSpacing(12)

        lbl_model = _i18n.ui(QLabel("Mô hình AI:", settings_card))
        lbl_model.setProperty("class", "fieldLabel")
        s_layout.addWidget(lbl_model, 0, 0)

        self.combo_model = QComboBox(settings_card)
        saved_model = (
            self.services.settings.get("gemini_model")
            if self.services.settings
            else None
        )
        try:
            models = self.services.generator.list_models()
        except Exception:
            models = ["gemini-2.0-flash", "gemini-1.5-pro"]
        chosen, _ = select_preferred_model(models, saved_model)
        for m in models:
            self.combo_model.addItem(m, m)
        idx = self.combo_model.findData(chosen)
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
        s_layout.addWidget(self.combo_model, 0, 1)

        lbl_tone = _i18n.ui(QLabel("Phong cách viết:", settings_card))
        lbl_tone.setProperty("class", "fieldLabel")
        s_layout.addWidget(lbl_tone, 0, 2)

        self.combo_tone = QComboBox(settings_card)
        _i18n.add_item(self.combo_tone, "Hấp dẫn & Cuốn hút (Click-worthy)", "engaging")
        _i18n.add_item(self.combo_tone, "Hài hước & Thân thiện", "humorous")
        _i18n.add_item(self.combo_tone, "Chuyên nghiệp & Chuẩn SEO", "seo")
        s_layout.addWidget(self.combo_tone, 0, 3)

        settings_card.add_layout(s_layout)

        btn_row = QHBoxLayout()
        self.btn_generate = _i18n.ui(AppButton("Tạo nội dung AI ngay", variant="primary", icon_name="creation", parent=settings_card))
        self.btn_generate.clicked.connect(self._on_generate)
        btn_row.addWidget(self.btn_generate)

        self.btn_restore = _i18n.ui(AppButton("Khôi phục tiêu đề gốc", variant="secondary", icon_name="history", parent=settings_card))
        self.btn_restore.clicked.connect(lambda: self.state.restore_original())
        btn_row.addWidget(self.btn_restore)

        self.btn_copy = _i18n.ui(AppButton("Sao chép tất cả", variant="secondary", icon_name="content-copy", parent=settings_card))
        self.btn_copy.clicked.connect(self._on_copy_all)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch()

        settings_card.add_layout(btn_row)

        self.progress_bar = QProgressBar(settings_card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        settings_card.add_widget(self.progress_bar)

        layout.addWidget(settings_card)

        # Editor Card
        editor_card = Card(title="Biên tập nội dung đã sinh", parent=container)
        e_layout = QVBoxLayout()
        e_layout.setSpacing(12)

        title_header = QHBoxLayout()
        lbl_t = _i18n.ui(QLabel("Tiêu đề YouTube (Tối đa 100 ký tự):", editor_card))
        lbl_t.setProperty("class", "fieldLabel")
        title_header.addWidget(lbl_t)
        title_header.addStretch()

        self.lbl_counter = _i18n.ui(QLabel("0/100 ký tự", editor_card))
        self.lbl_counter.setProperty("class", "charCounter")
        title_header.addWidget(self.lbl_counter)
        e_layout.addLayout(title_header)

        self.edit_title = QLineEdit(editor_card)
        _i18n.placeholder(self.edit_title, "Tiêu đề video...")
        self.edit_title.textChanged.connect(self._on_title_changed)
        e_layout.addWidget(self.edit_title)

        lbl_d = _i18n.ui(QLabel("Mô tả video:", editor_card))
        lbl_d.setProperty("class", "fieldLabel")
        e_layout.addWidget(lbl_d)

        self.edit_desc = QTextEdit(editor_card)
        self.edit_desc.setMinimumHeight(140)
        _i18n.placeholder(self.edit_desc, "Mô tả chi tiết video...")
        self.edit_desc.textChanged.connect(lambda: setattr(self.state, "description", self.edit_desc.toPlainText()))
        e_layout.addWidget(self.edit_desc)

        tag_grid = QGridLayout()
        tag_grid.setSpacing(10)

        lbl_h = QLabel("Hashtags:", editor_card)
        lbl_h.setProperty("class", "fieldLabel")
        tag_grid.addWidget(lbl_h, 0, 0)

        self.edit_hashtags = QLineEdit(editor_card)
        self.edit_hashtags.setPlaceholderText("shorts trending fyp...")
        self.edit_hashtags.textChanged.connect(self._on_hashtags_changed)
        tag_grid.addWidget(self.edit_hashtags, 1, 0)

        lbl_tg = _i18n.ui(QLabel("Thẻ tìm kiếm (Tags):", editor_card))
        lbl_tg.setProperty("class", "fieldLabel")
        tag_grid.addWidget(lbl_tg, 0, 1)

        self.edit_tags = QLineEdit(editor_card)
        self.edit_tags.setPlaceholderText("tag1, tag2, tag3...")
        self.edit_tags.textChanged.connect(self._on_tags_changed)
        tag_grid.addWidget(self.edit_tags, 1, 1)

        e_layout.addLayout(tag_grid)
        editor_card.add_layout(e_layout)
        layout.addWidget(editor_card)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _connect_state(self) -> None:
        self.state.job_changed.connect(self._sync_state)

    def _sync_state(self) -> None:
        if self.edit_title.text() != self.state.title:
            self.edit_title.blockSignals(True)
            self.edit_title.setText(self.state.title)
            self.edit_title.blockSignals(False)
            self._update_counter(self.state.title)

        if self.edit_desc.toPlainText() != self.state.description:
            self.edit_desc.blockSignals(True)
            self.edit_desc.setPlainText(self.state.description)
            self.edit_desc.blockSignals(False)

        h_text = format_hashtags(self.state.hashtags)
        if self.edit_hashtags.text() != h_text:
            self.edit_hashtags.blockSignals(True)
            self.edit_hashtags.setText(h_text)
            self.edit_hashtags.blockSignals(False)

        t_text = ", ".join(self.state.tags)
        if self.edit_tags.text() != t_text:
            self.edit_tags.blockSignals(True)
            self.edit_tags.setText(t_text)
            self.edit_tags.blockSignals(False)

    def _update_counter(self, text: str) -> None:
        c = len(text)
        _i18n.format_text(self.lbl_counter, '{0}/100 ký tự', f'{c}')
        if c > 100:
            self.lbl_counter.setProperty("class", "charCounterDanger")
        elif c >= 90:
            self.lbl_counter.setProperty("class", "charCounterWarn")
        else:
            self.lbl_counter.setProperty("class", "charCounter")
        self.lbl_counter.style().unpolish(self.lbl_counter)
        self.lbl_counter.style().polish(self.lbl_counter)

    @Slot(str)
    def _on_title_changed(self, text: str) -> None:
        self.state.title = text
        self._update_counter(text)

    @Slot(str)
    def _on_hashtags_changed(self, text: str) -> None:
        self.state.hashtags = [h.lstrip("#") for h in text.replace(",", " ").split() if h.strip()]

    @Slot(str)
    def _on_tags_changed(self, text: str) -> None:
        self.state.tags = [t.strip() for t in text.split(",") if t.strip()]

    @Slot()
    def _on_generate(self) -> None:
        if not self.state.meta:
            QMessageBox.warning(self, "Chưa có video", "Vui lòng chọn hoặc tải video trước khi sinh nội dung.")
            return

        self.btn_generate.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(20)

        # UI Safety watchdog timer (65s)
        self._ai_timer = QTimer(self)
        self._ai_timer.setSingleShot(True)
        self._ai_timer.timeout.connect(self._on_ui_timeout)
        self._ai_timer.start(65000)

        settings = {
            "model": self.combo_model.currentData() or "gemini-2.0-flash",
            "tone": self.combo_tone.currentData() or "engaging",
            "video_path": str(self.state.local_video_path) if self.state.local_video_path else None,
        }

        worker = GenerateContentWorker(self.services.generator, self.state.meta, settings)
        worker.signals.model_selected.connect(self.services.gemini_selection.changed)
        worker.signals.progress.connect(lambda p: self.progress_bar.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_finished)
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
    def _on_finished(self, content: GeneratedContent) -> None:
        if hasattr(self, "_ai_timer") and self._ai_timer.isActive():
            self._ai_timer.stop()
        self.progress_bar.setValue(100)
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.state.set_generated_content(content)
        self._notify("success", "Tạo nội dung hoàn tất", "Đã tạo nội dung AI thành công!")

    @Slot(str)
    def _on_error(self, err: str) -> None:
        if hasattr(self, "_ai_timer") and self._ai_timer.isActive():
            self._ai_timer.stop()
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._notify("error", "Lỗi tạo nội dung", f"Lỗi sinh nội dung AI: {err}")

    @Slot()
    def _on_ui_timeout(self) -> None:
        if not self.btn_generate.isEnabled():
            self.progress_bar.setVisible(False)
            self.btn_generate.setEnabled(True)
            self._notify(
                "error",
                "Quá thời gian phản hồi",
                "Quá thời gian chờ tạo nội dung AI (timeout 60 giây). "
                "Thao tác đã bị dừng. Vui lòng kiểm tra lại kết nối mạng hoặc thử lại sau.",
            )

    @Slot()
    def _on_copy_all(self) -> None:
        text = f"{self.state.title}\n\n{self.state.description}\n\n"
        if self.state.hashtags:
            text += " ".join(f"#{t}" for t in self.state.hashtags) + "\n"
        QGuiApplication.clipboard().setText(text)
        self._notify("info", "Đã sao chép", "Đã sao chép nội dung vào bộ nhớ tạm.")


    @Slot(str, str)
    def _on_model_selected(self, model, message):
        self.services.settings.set('gemini_model', model)
        self.lbl_model_notice.setText(message)
        index = self.combo_model.findData(model)
        if index < 0:
            self.combo_model.addItem(model, model)
            index = self.combo_model.count() - 1
        self.combo_model.setCurrentIndex(index)
