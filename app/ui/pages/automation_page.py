"""Manage saved automation prompts; execution remains on Dashboard."""
from __future__ import annotations

from typing import Optional
from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog,
    QLineEdit, QTextEdit, QCheckBox, QComboBox, QTableWidget, QHeaderView,
    QAbstractItemView, QScrollArea, QFrame, QSizePolicy, QPushButton
)
from app.ui import i18n as _i18n
from app.core.automation import AutomationPolicy
from app.services.gemini.automation import GeminiPromptInterpreter
from app.ui import icons, tokens
from app.ui.components import AppButton, Card, ConfirmDialog, EmptyState, StatusBadge, ToastManager
from app.workers.automation_workers import InterpretPromptWorker


def _default_account(services):
    return next((account for account in services.connection.accounts if account.is_default), None)


def _channel_combo(services, selected, parent):
    combo = QComboBox(parent)
    default = _default_account(services)
    suffix = default.title if default else 'chưa có kênh mặc định'
    combo.addItem('Tự động — ' + suffix, None)
    for account in services.connection.accounts:
        if account.status == 'connected':
            combo.addItem(account.title, account.id)
    index = combo.findData(selected)
    if selected is not None and index < 0:
        combo.addItem('Kênh không còn kết nối · ' + selected, selected)
        index = combo.count() - 1
    combo.setCurrentIndex(max(0, index))
    return combo


class _PreviewInterpreter:
    def interpret(self, _prompt):
        # Explicit demo policy; never represented as real AI interpretation.
        return AutomationPolicy()


class AddPromptDialog(QDialog):
    def __init__(self, services, store, parent=None, interpreter=None):
        super().__init__(parent)
        _i18n.title(self, 'Thêm prompt tự động hóa')
        self.resize(660, 640)
        self.store, self.services = store, services
        self.interpreter = interpreter or (_PreviewInterpreter() if services.is_fake else GeminiPromptInterpreter(services.secrets, services.settings))
        self.policy = None
        self._worker = None

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {tokens.BG_MODAL};
            }}
            QLineEdit, QTextEdit {{
                background-color: {tokens.BG_INPUT};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 10px 12px;
                color: {tokens.TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {tokens.BORDER_FOCUS};
                background-color: {tokens.BG_INPUT_FOCUS};
            }}
            QComboBox {{
                background-color: {tokens.BG_INPUT};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px 12px;
                color: {tokens.TEXT_PRIMARY};
                font-size: 13px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = _i18n.ui(QLabel('Thêm quy trình tự động hóa mới', self))
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(title)

        intro = _i18n.ui(QLabel('Nhập yêu cầu bằng tiếng Việt tự nhiên: AI sẽ tự phân tích cách tải TikTok, tối ưu SEO, chế độ đăng/hẹn giờ và đối tượng trẻ em.', self))
        intro.setStyleSheet(f"font-size: 12px; color: {tokens.TEXT_SECONDARY}; line-height: 1.4;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if services.is_fake:
            demo_frame = QFrame(self)
            demo_frame.setStyleSheet(f"background-color: {tokens.WARNING_BG}; border: 1px solid {tokens.WARNING_BORDER}; border-radius: 6px; padding: 6px 10px;")
            demo_layout = QHBoxLayout(demo_frame)
            demo_layout.setContentsMargins(4, 4, 4, 4)
            demo = _i18n.ui(QLabel('CHẾ ĐỘ GIẢ LẬP: Dùng cấu hình mẫu riêng tư, không phân tích AI thật hay tải lên thật.', demo_frame))
            demo.setStyleSheet(f"color: #fde68a; font-size: 12px; font-weight: 600;")
            demo.setWordWrap(True)
            demo_layout.addWidget(demo)
            layout.addWidget(demo_frame)

        # Name edit
        name_lbl = _i18n.ui(QLabel('Tên prompt gợi nhớ:', self))
        name_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(name_lbl)
        self.name_edit = QLineEdit(self)
        _i18n.placeholder(self.name_edit, 'Ví dụ: Đăng tự động mỗi 1 tiếng, Đăng công khai ngay...')
        layout.addWidget(self.name_edit)

        channel_row = QHBoxLayout()
        ch_lbl = _i18n.ui(QLabel('Kênh xuất bản:', self))
        ch_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        channel_row.addWidget(ch_lbl)
        self.combo_channel = _channel_combo(services, None, self)
        channel_row.addWidget(self.combo_channel, 1)
        layout.addLayout(channel_row)

        # Prompt edit
        prompt_lbl = _i18n.ui(QLabel('Yêu cầu tự động hóa (Prompt):', self))
        prompt_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(prompt_lbl)
        self.prompt_edit = QTextEdit(self)
        _i18n.placeholder(self.prompt_edit, 'Khi tôi dán link TikTok ở tab Tổng quan, tự động tải video, dùng AI tạo tiêu đề & mô tả, và hẹn giờ công khai mỗi 60 phút, không dành cho trẻ em.')
        self.prompt_edit.setMinimumHeight(110)
        layout.addWidget(self.prompt_edit)

        # Quick preset buttons
        preset_box = QHBoxLayout()
        preset_box.setSpacing(8)
        preset_label = _i18n.ui(QLabel('Gợi ý mẫu nhanh:', self))
        preset_label.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED};")
        preset_box.addWidget(preset_label)

        btn_preset1 = _i18n.ui(AppButton('Hẹn giờ mỗi 60p', variant='ghost', parent=self))
        btn_preset1.setStyleSheet(f"font-size: 11px; padding: 4px 10px; border: 1px solid {tokens.BORDER_SUBTLE}; border-radius: 4px;")
        btn_preset1.clicked.connect(lambda: self._apply_preset(
            'Hẹn giờ công khai 60 phút',
            'Khi tôi dán link TikTok, tự động tải video, tạo nội dung AI chuẩn SEO và hẹn giờ công khai mỗi 60 phút, không dành cho trẻ em.'
        ))
        preset_box.addWidget(btn_preset1)

        btn_preset2 = _i18n.ui(AppButton('Đăng riêng tư ngay', variant='ghost', parent=self))
        btn_preset2.setStyleSheet(f"font-size: 11px; padding: 4px 10px; border: 1px solid {tokens.BORDER_SUBTLE}; border-radius: 4px;")
        btn_preset2.clicked.connect(lambda: self._apply_preset(
            'Đăng riêng tư tức thì',
            'Khi dán link TikTok, tự động tải video, dùng AI tối ưu nội dung và đăng riêng tư ngay lập tức, không dành cho trẻ em.'
        ))
        preset_box.addWidget(btn_preset2)
        preset_box.addStretch()
        layout.addLayout(preset_box)

        # Result / summary frame
        self.summary_frame = QFrame(self)
        self.summary_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {tokens.BG_CARD};
                border: 1px dashed {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 12px 14px;
            }}
        """)
        sum_layout = QVBoxLayout(self.summary_frame)
        sum_layout.setContentsMargins(0, 0, 0, 0)
        sum_layout.setSpacing(4)

        sum_title = _i18n.ui(QLabel('Kết quả phân tích từ AI:', self.summary_frame))
        sum_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {tokens.TEXT_MUTED}; text-transform: uppercase;")
        sum_layout.addWidget(sum_title)

        self.summary = _i18n.ui(QLabel('Bấm "Phân tích prompt" để AI đọc hiểu và trích xuất cấu hình tự động trước khi lưu.', self.summary_frame))
        self.summary.setStyleSheet(f"font-size: 12px; color: {tokens.TEXT_SECONDARY}; line-height: 1.4;")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        sum_layout.addWidget(self.summary)
        layout.addWidget(self.summary_frame)

        # Actions
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.analyze_button = _i18n.ui(AppButton('Phân tích prompt', variant='secondary', icon_name='sparkle', parent=self))
        self.analyze_button.clicked.connect(self._analyze)
        buttons.addWidget(self.analyze_button)

        buttons.addStretch()

        btn_cancel = _i18n.ui(AppButton('Hủy bỏ', variant='ghost', parent=self))
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)

        self.save_button = _i18n.ui(AppButton('Lưu quy trình', variant='primary', icon_name='check', parent=self))
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)

        layout.addLayout(buttons)
        self.prompt_edit.textChanged.connect(self._invalidate)

    def _apply_preset(self, name: str, prompt: str) -> None:
        self.name_edit.setText(name)
        self.prompt_edit.setPlainText(prompt)

    def _invalidate(self):
        self.policy = None
        self.save_button.setEnabled(False)
        self.summary_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {tokens.BG_CARD};
                border: 1px dashed {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 12px 14px;
            }}
        """)

    def _analyze(self):
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt or not self.name_edit.text().strip():
            _i18n.set_text(self.summary, 'Vui lòng nhập đầy đủ tên và nội dung prompt trước khi phân tích.')
            return
        self._analyzed_prompt = prompt
        self.prompt_edit.setReadOnly(True)
        self.analyze_button.setEnabled(False)
        self.summary.setText('Đang gửi prompt đến Gemini AI để phân tích quy tắc cấu hình…' if not self.services.is_fake else 'Đang chuẩn bị cấu hình giả lập…')
        self._worker = InterpretPromptWorker(self.interpreter, prompt)
        self._worker.signals.finished.connect(self._analyzed)
        self._worker.signals.error.connect(self._error)
        QThreadPool.globalInstance().start(self._worker)

    @Slot(object)
    def _analyzed(self, policy):
        self.prompt_edit.setReadOnly(False)
        self.analyze_button.setEnabled(True)
        self.policy = policy
        self.summary.setText(policy.summary())
        self.summary_frame.setStyleSheet(f"""
            QFrame {{
                background-color: #121e2a;
                border: 1px solid {tokens.PRIMARY};
                border-radius: 8px;
                padding: 12px 14px;
            }}
        """)
        self.save_button.setEnabled(True)
        self._worker = None

    @Slot(str)
    def _error(self, message):
        self.prompt_edit.setReadOnly(False)
        self.analyze_button.setEnabled(True)
        _i18n.format_text(self.summary, 'Lỗi phân tích: {0}', f'{message}')
        self.summary_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {tokens.DANGER_BG};
                border: 1px solid {tokens.DANGER_BORDER};
                border-radius: 8px;
                padding: 12px 14px;
            }}
        """)
        self._worker = None

    def _save(self):
        if self.policy is None or self.prompt_edit.toPlainText().strip() != self._analyzed_prompt:
            self._invalidate()
            return
        try:
            self.store.add_prompt(
                self.name_edit.text().strip(),
                self._analyzed_prompt,
                self.policy,
                target_channel_id=self.combo_channel.currentData()
            )
        except Exception:
            _i18n.set_text(self.summary, 'Không lưu được prompt. Kiểm tra tên, nội dung hoặc dữ liệu nhạy cảm rồi thử lại.')
            return
        self.accept()


class ActivatePromptDialog(QDialog):
    def __init__(self, prompt, accounts, parent=None):
        super().__init__(parent)
        _i18n.title(self, 'Bật tự động hóa')
        self.resize(580, 420)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {tokens.BG_MODAL};
            }}
            QComboBox {{
                background-color: {tokens.BG_INPUT};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px 12px;
                color: {tokens.TEXT_PRIMARY};
                font-size: 13px;
            }}
            QCheckBox {{
                color: {tokens.TEXT_PRIMARY};
                font-size: 13px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {tokens.BORDER_DEFAULT};
                background: {tokens.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background-color: {tokens.PRIMARY};
                border-color: {tokens.PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = _i18n.formatted(QLabel('', self), 'Kích hoạt: {0}', f"{prompt['name']}")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(title)

        # Policy overview box
        overview_card = QFrame(self)
        overview_card.setStyleSheet(f"""
            QFrame {{
                background-color: {tokens.BG_CARD};
                border: 1px solid {tokens.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 10px 14px;
            }}
        """)
        ov_layout = QVBoxLayout(overview_card)
        ov_layout.setContentsMargins(0, 0, 0, 0)
        ov_layout.setSpacing(4)
        ov_title = _i18n.ui(QLabel('Cấu hình thực thi:', overview_card))
        ov_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {tokens.BRAND_MINT}; text-transform: uppercase;")
        ov_layout.addWidget(ov_title)

        summary = QLabel(prompt['policy'].summary(), overview_card)
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px; line-height: 1.4;")
        summary.setWordWrap(True)
        ov_layout.addWidget(summary)
        layout.addWidget(overview_card)

        # Destination channel
        ch_label = _i18n.ui(QLabel('Chọn kênh YouTube đích cho phiên này:', self))
        ch_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(ch_label)

        self.channels = QComboBox(self)
        for account in accounts:
            if account.status == 'connected':
                self.channels.addItem(f"{account.title} ({account.id})", account.id)
        layout.addWidget(self.channels)

        # Terms / consents
        consent_frame = QFrame(self)
        consent_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {tokens.BG_INPUT};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        consent_layout = QVBoxLayout(consent_frame)
        consent_layout.setContentsMargins(0, 0, 0, 0)
        consent_layout.setSpacing(10)

        self.rights = _i18n.ui(QCheckBox('Tôi cam kết có quyền sử dụng hợp pháp các video đưa vào chế độ này.', consent_frame))
        self.permission = _i18n.ui(QCheckBox('Tôi cho phép tự động tải lên kênh YouTube theo prompt, không cần duyệt tay từng video.', consent_frame))
        _i18n.tooltip(self.permission, 'Quyền này sẽ tự động hết hiệu lực khi bạn tắt prompt hoặc đóng ứng dụng.')
        consent_layout.addWidget(self.rights)
        consent_layout.addWidget(self.permission)
        layout.addWidget(consent_frame)

        note = _i18n.ui(QLabel('Lưu ý an toàn: Khi tắt hoặc gặp lỗi, ứng dụng sẽ dừng tự động ngay lập tức. Mở lại app cần bật lại.', self))
        note.setStyleSheet(f"color: {tokens.TEXT_MUTED}; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addSpacing(6)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        btn_cancel = _i18n.ui(AppButton('Hủy', variant='ghost', parent=self))
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.activate_button = _i18n.ui(AppButton('Kích hoạt Hoạt động', variant='primary', icon_name='check', parent=self))
        self.activate_button.setEnabled(False)
        self.activate_button.clicked.connect(self.accept)
        btn_box.addWidget(self.activate_button)
        layout.addLayout(btn_box)

        self.rights.toggled.connect(self._validate)
        self.permission.toggled.connect(self._validate)

    def _validate(self):
        self.activate_button.setEnabled(self.channels.count() > 0 and self.rights.isChecked() and self.permission.isChecked())


class AutomationCardWidget(QFrame):
    """Modern card representation of a single automation prompt rule."""

    def __init__(self, prompt: dict, is_active: bool, next_slot_str: Optional[str],
                 on_toggle, on_delete, parent=None, services=None, busy: bool = False,
                 on_channel_changed=None):
        super().__init__(parent)
        self.prompt = prompt
        self.is_active = is_active

        # Card container styling
        border_color = "#3b82f6" if is_active else "#273148"
        bg_color = "#151b2b" if is_active else "#131722"
        self.setStyleSheet(f"""
            QFrame#automationCard {{
                background-color: {bg_color};
                border: 1.5px solid {border_color};
                border-radius: 12px;
            }}
        """)
        self.setObjectName("automationCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # 1. Header: Icon + Name + Status + CTA Action Buttons
        header = QHBoxLayout()
        header.setSpacing(14)

        # Vector Icon Box (Sparkle / Creation)
        icon_box = QLabel(self)
        icon_box.setFixedSize(44, 44)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if is_active:
            icon_box.setStyleSheet("""
                background-color: #1e3a8a;
                border: 1.5px solid #3b82f6;
                border-radius: 22px;
            """)
            icon_box.setPixmap(icons.get_icon("sparkle", color="#ffffff").pixmap(24, 24))
        else:
            icon_box.setStyleSheet("""
                background-color: #1c2333;
                border: 1px solid #2e3b54;
                border-radius: 22px;
            """)
            icon_box.setPixmap(icons.get_icon("sparkle", color="#728BFF").pixmap(22, 22))
        header.addWidget(icon_box)

        # Name and status badge
        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        name_lbl = QLabel(prompt['name'], self)
        name_lbl.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {tokens.TEXT_PRIMARY}; border: none; background: transparent;")
        info_col.addWidget(name_lbl)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        if is_active:
            badge = StatusBadge(status="ĐANG HOẠT ĐỘNG", badge_type="success", parent=self)
            sub_row.addWidget(badge)
            lbl_channel = _i18n.ui(QLabel("• Sẵn sàng chạy khi dán link TikTok", self))
            lbl_channel.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {tokens.BRAND_MINT}; border: none; background: transparent;")
            sub_row.addWidget(lbl_channel)
        else:
            badge = StatusBadge(status="ĐÃ TẮT", badge_type="warning", parent=self)
            _i18n.set_text(badge.lbl_text, "ĐÃ TẮT")
            sub_row.addWidget(badge)
            lbl_inactive = _i18n.ui(QLabel("• Tạm dừng", self))
            lbl_inactive.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED}; border: none; background: transparent;")
            sub_row.addWidget(lbl_inactive)
        sub_row.addStretch()
        info_col.addLayout(sub_row)
        header.addLayout(info_col, 1)

        # Action Buttons (Highly Visible CTA)
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        # Primary Toggle Button
        btn_toggle = QPushButton(self)
        btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_active:
            _i18n.set_text(btn_toggle, "  Tắt hoạt động")
            btn_toggle.setIcon(icons.get_icon("pause", color="#f87171"))
            btn_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #2c151c;
                    color: #fca5a5;
                    font-size: 13px;
                    font-weight: 700;
                    border: 1.5px solid #f43f5e;
                    border-radius: 8px;
                    padding: 8px 18px;
                }
                QPushButton:hover {
                    background-color: #3d1723;
                    border-color: #fb7185;
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background-color: #4c1d2c;
                }
            """)
        else:
            _i18n.set_text(btn_toggle, "  Bật hoạt động")
            btn_toggle.setIcon(icons.get_icon("play", color="#ffffff"))
            btn_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #2563eb;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: 700;
                    border: 1px solid #3b82f6;
                    border-radius: 8px;
                    padding: 8px 20px;
                }
                QPushButton:hover {
                    background-color: #1d4ed8;
                    border-color: #60a5fa;
                }
                QPushButton:pressed {
                    background-color: #1e40af;
                }
            """)
        btn_toggle.clicked.connect(on_toggle)
        btn_box.addWidget(btn_toggle)

        # Delete Button
        btn_delete = QPushButton(self)
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        _i18n.set_text(btn_delete, "  Xóa")
        btn_delete.setIcon(icons.get_icon("delete", color="#94a3b8"))
        btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #1c2233;
                color: #94a3b8;
                font-size: 13px;
                font-weight: 600;
                border: 1px solid #2a344c;
                border-radius: 8px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background-color: #301a21;
                border-color: #ef4444;
                color: #f87171;
            }
            QPushButton:pressed {
                background-color: #3f1e28;
            }
        """)
        btn_delete.clicked.connect(on_delete)
        btn_box.addWidget(btn_delete)

        header.addLayout(btn_box)
        layout.addLayout(header)

        # 2. Integrated Channel Selection Bar
        if services is not None:
            channel_bar = QFrame(self)
            channel_bar.setStyleSheet("""
                QFrame {
                    background-color: #101420;
                    border: 1px solid #1c2336;
                    border-radius: 8px;
                    padding: 6px 12px;
                }
            """)
            ch_layout = QHBoxLayout(channel_bar)
            ch_layout.setContentsMargins(4, 2, 4, 2)
            ch_layout.setSpacing(10)

            icon_yt = QLabel(channel_bar)
            icon_yt.setPixmap(icons.get_icon("youtube", color="#ef4444").pixmap(20, 20))
            ch_layout.addWidget(icon_yt)

            lbl_ch_title = _i18n.ui(QLabel('Kênh xuất bản:', channel_bar))
            lbl_ch_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #94a3b8; border: none; background: transparent;")
            ch_layout.addWidget(lbl_ch_title)

            self.combo_channel = _channel_combo(services, prompt.get('target_channel_id'), channel_bar)
            self.combo_channel.setMinimumWidth(260)
            self.combo_channel.setMaximumWidth(460)
            self.combo_channel.setEnabled(not is_active and not busy)
            self.combo_channel.setStyleSheet(f"""
                QComboBox {{
                    background-color: #171f30;
                    border: 1px solid #29364f;
                    border-radius: 6px;
                    padding: 4px 10px;
                    color: {tokens.TEXT_PRIMARY};
                    font-size: 12px;
                    font-weight: 500;
                    min-height: 26px;
                }}
                QComboBox:hover {{
                    border-color: {tokens.PRIMARY};
                }}
                QComboBox:disabled {{
                    color: {tokens.TEXT_MUTED};
                    background-color: #121622;
                }}
            """)
            _i18n.tooltip(self.combo_channel, 'Tự động dùng kênh mặc định trong mục Kênh YouTube. Tắt prompt trước khi đổi kênh.')
            ch_layout.addWidget(self.combo_channel)

            lbl_hint = _i18n.ui(QLabel('(Chọn kênh riêng cho prompt này hoặc để mặc định)', channel_bar))
            lbl_hint.setStyleSheet("font-size: 11px; color: #64748b; border: none; background: transparent;")
            ch_layout.addWidget(lbl_hint)
            ch_layout.addStretch()

            if on_channel_changed is not None:
                self.combo_channel.currentIndexChanged.connect(
                    lambda _index: on_channel_changed(self.combo_channel.currentData()))
            layout.addWidget(channel_bar)

        # 3. Body: 2 Columns (User Prompt & Clean Vector AI Config)
        body = QHBoxLayout()
        body.setSpacing(14)

        # Panel 1: User Prompt
        panel_prompt = QFrame(self)
        panel_prompt.setStyleSheet("""
            QFrame {
                background-color: #0f131f;
                border: 1px solid #1a2235;
                border-radius: 10px;
                padding: 14px 16px;
            }
        """)
        col_p = QVBoxLayout(panel_prompt)
        col_p.setContentsMargins(0, 0, 0, 0)
        col_p.setSpacing(10)

        header_p = QHBoxLayout()
        header_p.setSpacing(6)
        dot_p = QLabel(panel_prompt)
        dot_p.setFixedSize(6, 6)
        dot_p.setStyleSheet("background-color: #64748b; border-radius: 3px; border: none;")
        header_p.addWidget(dot_p)
        title_p = _i18n.ui(QLabel("YÊU CẦU CỦA BẠN (PROMPT)", panel_prompt))
        title_p.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; border: none; background: transparent;")
        header_p.addWidget(title_p)
        header_p.addStretch()
        col_p.addLayout(header_p)

        desc_p = QLabel(prompt['prompt'], panel_prompt)
        desc_p.setStyleSheet(f"font-size: 12.5px; color: {tokens.TEXT_PRIMARY}; line-height: 1.5; border: none; background: transparent;")
        desc_p.setWordWrap(True)
        desc_p.setTextFormat(Qt.TextFormat.PlainText)
        col_p.addWidget(desc_p)
        col_p.addStretch()
        body.addWidget(panel_prompt, 1)

        # Panel 2: AI Understood Configuration (Using Clean Vector Icons)
        panel_ai = QFrame(self)
        panel_ai.setStyleSheet("""
            QFrame {
                background-color: #101625;
                border: 1px solid #1c273e;
                border-radius: 10px;
                padding: 14px 16px;
            }
        """)
        col_ai = QVBoxLayout(panel_ai)
        col_ai.setContentsMargins(0, 0, 0, 0)
        col_ai.setSpacing(9)

        header_ai = QHBoxLayout()
        header_ai.setSpacing(6)
        icon_sparkle = QLabel(panel_ai)
        icon_sparkle.setPixmap(icons.get_icon("sparkle", color=tokens.BRAND_MINT).pixmap(16, 16))
        header_ai.addWidget(icon_sparkle)
        title_ai = _i18n.ui(QLabel("CẤU HÌNH THỰC THI (AI PARSED)", panel_ai))
        title_ai.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {tokens.BRAND_MINT}; text-transform: uppercase; border: none; background: transparent;")
        header_ai.addWidget(title_ai)
        header_ai.addStretch()
        col_ai.addLayout(header_ai)

        policy: AutomationPolicy = prompt['policy']

        # Determine specs
        if policy.interval_minutes is not None:
            spec_mode = "Tải lên riêng tư  →  Tự động công khai theo lịch"
            spec_interval = f"Hẹn giờ mỗi {policy.interval_minutes} phút (từ {policy.start_hour:02d}:{policy.start_minute:02d} UTC+7)"
        else:
            p_map = {'private': 'Riêng tư', 'public': 'Công khai', 'unlisted': 'Không công khai'}
            spec_mode = f"Đăng ngay lập tức ({p_map.get(policy.privacy, policy.privacy)})"
            spec_interval = "Đăng ngay không hẹn giờ"

        spec_kids = "Dành cho trẻ em" if policy.made_for_kids else "Không dành cho trẻ em"
        spec_pipe = "Tải TikTok  →  Tạo nội dung AI  →  Tải lên YouTube"

        # Build clean vector icon rows
        items = [
            ("shield", "#38bdf8", "Chế độ:", spec_mode),
            ("clock", "#fbbf24", "Tần suất:", spec_interval),
            ("user-check", "#c084fc", "Khán giả:", spec_kids),
            ("sync", "#59E3C1", "Quy trình:", spec_pipe),
        ]

        for icon_key, icon_color, label_prefix, label_val in items:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            ic_lbl = QLabel(panel_ai)
            ic_lbl.setFixedSize(18, 18)
            ic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic_lbl.setPixmap(icons.get_icon(icon_key, color=icon_color).pixmap(16, 16))
            ic_lbl.setStyleSheet("border: none; background: transparent;")
            row_layout.addWidget(ic_lbl)

            lbl_desc = QLabel(f"<span style='color: #64748b;'>{label_prefix}</span> <b style='color: #e2e8f0;'>{label_val}</b>", panel_ai)
            lbl_desc.setStyleSheet("font-size: 12px; border: none; background: transparent;")
            lbl_desc.setWordWrap(True)
            row_layout.addWidget(lbl_desc, 1)

            col_ai.addLayout(row_layout)

        # Highlight next slot schedule
        if next_slot_str:
            slot_frame = QFrame(panel_ai)
            slot_frame.setStyleSheet("""
                QFrame {
                    background-color: #221c10;
                    border: 1px solid #785715;
                    border-radius: 6px;
                    padding: 6px 12px;
                }
            """)
            slot_layout = QHBoxLayout(slot_frame)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.setSpacing(8)

            ic_clock = QLabel(slot_frame)
            ic_clock.setPixmap(icons.get_icon("clock", color="#f59e0b").pixmap(16, 16))
            ic_clock.setStyleSheet("border: none; background: transparent;")
            slot_layout.addWidget(ic_clock)

            slot_lbl = _i18n.formatted(QLabel('', slot_frame), "Khung giờ đăng kế tiếp: <b style='color: #fef08a;'>{0}</b>", f'{next_slot_str}')
            slot_lbl.setStyleSheet("font-size: 12px; color: #fde68a; border: none; background: transparent;")
            slot_layout.addWidget(slot_lbl)
            slot_layout.addStretch()

            col_ai.addWidget(slot_frame)

        col_ai.addStretch()
        body.addWidget(panel_ai, 1)

        layout.addLayout(body)


class AutomationPage(QWidget):
    def __init__(self, services, controller, parent=None):
        super().__init__(parent)
        self.services, self.controller, self.store = services, controller, controller.store

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(16)

        # 1. Header Layout
        header = QHBoxLayout()
        header.setSpacing(12)

        header_text_col = QVBoxLayout()
        header_text_col.setSpacing(3)

        title = _i18n.ui(QLabel('Tự động hóa thông minh', self))
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {tokens.TEXT_PRIMARY};")
        header_text_col.addWidget(title)

        subtitle = _i18n.ui(QLabel('Tự động hóa toàn bộ quy trình: Dán link TikTok → Tải video → Tạo tiêu đề SEO bằng Gemini → Xuất bản YouTube.', self))
        subtitle.setStyleSheet(f"font-size: 13px; color: {tokens.TEXT_SECONDARY};")
        header_text_col.addWidget(subtitle)
        header.addLayout(header_text_col, 1)

        self.add_button = _i18n.ui(AppButton('Thêm prompt', variant='primary', icon_name='sparkle', parent=self))
        self.add_button.clicked.connect(self._add)
        header.addWidget(self.add_button)
        root_layout.addLayout(header)

        # 2. System Status Banner Card
        self.banner_card = QFrame(self)
        self.banner_card.setObjectName("automationBanner")
        self.banner_card.setStyleSheet(f"""
            QFrame#automationBanner {{
                background-color: {tokens.BG_CARD};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: 12px;
            }}
        """)
        banner_layout = QHBoxLayout(self.banner_card)
        banner_layout.setContentsMargins(18, 14, 18, 14)
        banner_layout.setSpacing(14)

        # Status icon circle
        self.banner_icon = QLabel(self.banner_card)
        self.banner_icon.setFixedSize(42, 42)
        self.banner_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_icon.setStyleSheet(f"background-color: #1e2434; border-radius: 21px; border: none;")
        banner_layout.addWidget(self.banner_icon)

        # Status textual details
        banner_info = QVBoxLayout()
        banner_info.setSpacing(2)

        self.status = QLabel(self.banner_card)
        self.status.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {tokens.TEXT_PRIMARY}; border: none; background: transparent;")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        banner_info.addWidget(self.status)

        self.banner_hint = _i18n.ui(QLabel('Chọn kênh riêng cho từng prompt, hoặc để Tự động dùng kênh mặc định trong mục Kênh YouTube. Bật prompt rồi qua Tổng quan dán link.', self.banner_card))
        self.banner_hint.setStyleSheet(f"font-size: 12px; color: {tokens.TEXT_SECONDARY}; border: none; background: transparent;")
        self.banner_hint.setWordWrap(True)
        banner_info.addWidget(self.banner_hint)
        banner_layout.addLayout(banner_info, 1)

        # Right side: Last job info & quick turn-off
        right_box = QVBoxLayout()
        right_box.setSpacing(4)
        right_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.last_job = QLabel(self.banner_card)
        self.last_job.setTextFormat(Qt.TextFormat.PlainText)
        self.last_job.setStyleSheet(f"font-size: 12px; color: {tokens.TEXT_MUTED}; font-weight: 500; border: none; background: transparent;")
        right_box.addWidget(self.last_job)

        self.btn_banner_deactivate = _i18n.ui(QPushButton('Tắt tự động hóa', self.banner_card))
        self.btn_banner_deactivate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_banner_deactivate.setStyleSheet("""
            QPushButton {
                background-color: #2b161e;
                color: #fca5a5;
                font-size: 11px;
                font-weight: 600;
                border: 1px solid #f43f5e;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #3d1723;
                color: #ffffff;
            }
        """)
        self.btn_banner_deactivate.clicked.connect(self.controller.deactivate)
        self.btn_banner_deactivate.hide()
        right_box.addWidget(self.btn_banner_deactivate)

        banner_layout.addLayout(right_box)
        root_layout.addWidget(self.banner_card)

        # 3. Main Content: ScrollArea containing Prompt Cards
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.card_container = QWidget()
        self.card_container.setStyleSheet("background: transparent;")
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 4, 0, 4)
        self.card_layout.setSpacing(14)
        self.scroll_area.setWidget(self.card_container)
        root_layout.addWidget(self.scroll_area, 1)

        # Empty State
        btn_empty_add = _i18n.ui(AppButton('Tạo prompt tự động hóa', variant='primary', icon_name='sparkle'))
        btn_empty_add.clicked.connect(self._add)
        self.empty = EmptyState(
            icon_name='sparkle',
            title='Chưa có quy trình tự động hóa',
            description='Tạo prompt bằng tiếng Việt để Clivo tự động tải video từ liên kết TikTok, tạo tiêu đề & mô tả chuẩn SEO bằng Gemini AI và lên lịch đăng tải lên YouTube.',
            action_button=btn_empty_add,
            parent=self
        )
        root_layout.addWidget(self.empty, 1)

        # Hidden table widget for backward-compatibility with tests / internal tools
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        _i18n.headers(self.table, ['Prompt', 'Thiết lập AI đã hiểu', 'Trạng thái', 'Thao tác'])
        self.table.hide()
        root_layout.addWidget(self.table)

        controller.changed.connect(self.refresh)
        self.services.connection.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        prompts = self.store.list_prompts()
        active_pid = self.controller.armed_prompt_id
        is_system_active = active_pid is not None

        # Update Banner Card
        self.status.setText(self.controller.message)
        if is_system_active:
            active_prompt = next((p for p in prompts if p['id'] == active_pid), None)
            name = active_prompt['name'] if active_prompt else "Đang chạy"
            self.banner_icon.setStyleSheet("background-color: #064e3b; border-radius: 21px; border: 1.5px solid #10b981;")
            self.banner_icon.setPixmap(icons.get_icon("check", color="#ffffff").pixmap(22, 22))
            self.banner_card.setStyleSheet("""
                QFrame#automationBanner {{
                    background-color: #121e2a;
                    border: 1px solid #3b82f6;
                    border-radius: 12px;
                }}
            """)
            self.btn_banner_deactivate.show()
        else:
            self.banner_icon.setStyleSheet("background-color: #1a2033; border-radius: 21px; border: 1px solid #2e3a52;")
            self.banner_icon.setPixmap(icons.get_icon("sparkle", color="#728BFF").pixmap(20, 20))
            self.banner_card.setStyleSheet(f"""
                QFrame#automationBanner {{
                    background-color: {tokens.BG_CARD};
                    border: 1px solid {tokens.BORDER_DEFAULT};
                    border-radius: 12px;
                }}
            """)
            self.btn_banner_deactivate.hide()

        # Update Empty state vs Card Container
        has_prompts = bool(prompts)
        self.empty.setVisible(not has_prompts)
        self.scroll_area.setVisible(has_prompts)

        # Clear existing cards in layout
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

        # Render Prompt Cards
        default = _default_account(self.services)
        for prompt in prompts:
            is_active = prompt['id'] == active_pid
            selected_ch = (self.controller.channel_id if is_active else
                           prompt.get('target_channel_id') or (default.id if default else None))
            next_slot = self.store.next_slot(prompt['id'], selected_ch)
            next_slot_str = (next_slot.strftime('%H:%M %d/%m/%Y') + ' (UTC+7)') if next_slot else None

            card = AutomationCardWidget(
                prompt=prompt,
                is_active=is_active,
                next_slot_str=next_slot_str,
                on_toggle=lambda _checked=False, pid=prompt['id']: self._toggle(pid),
                on_delete=lambda _checked=False, pid=prompt['id']: self._delete(pid),
                parent=self.card_container,
                services=self.services,
                busy=self.controller.busy,
                on_channel_changed=lambda channel, pid=prompt['id']: self._set_prompt_channel(pid, channel)
            )
            self.card_layout.addWidget(card)

        self.card_layout.addStretch()

        # Keep hidden table updated for full compatibility
        self.table.setRowCount(len(prompts))
        for row, prompt in enumerate(prompts):
            lbl_p = QLabel(prompt['name'] + '\n' + prompt['prompt'], self.table)
            self.table.setCellWidget(row, 0, lbl_p)
            lbl_pol = QLabel(prompt['policy'].summary(), self.table)
            self.table.setCellWidget(row, 1, lbl_pol)
            is_active = prompt['id'] == active_pid
            lbl_st = QLabel('Hoạt động' if is_active else 'Tắt', self.table)
            self.table.setCellWidget(row, 2, lbl_st)

        # Update Last Job status
        jobs = self.store.list_jobs(limit=1)
        if jobs:
            names = {
                'done': 'Hoàn tất',
                'uploading': 'Đang tải lên YouTube',
                'downloading': 'Đang tải video TikTok',
                'generating': 'Đang tạo nội dung AI',
                'failed': 'Thất bại',
                'cancelled': 'Đã hủy',
                'uncertain': 'Cần kiểm tra lại lịch sử'
            }
            status_text = names.get(jobs[0]['status'], jobs[0]['status'])
            _i18n.format_text(self.last_job, 'Lần chạy gần nhất: {0}', f'{status_text}')
        else:
            _i18n.set_text(self.last_job, 'Lần chạy gần nhất: Chưa có tác vụ')

    def _add(self):
        dialog = AddPromptDialog(self.services, self.store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _toggle(self, prompt_id):
        if prompt_id == self.controller.armed_prompt_id:
            self.controller.deactivate()
            return
        if self.controller.busy:
            self._notice('Chờ tác vụ hiện tại dừng trước khi bật prompt khác.')
            return
        prompt = self.store.get_prompt(prompt_id)
        default = _default_account(self.services)
        channel_id = prompt.get('target_channel_id') or (default.id if default else None)
        if not channel_id:
            self._notice('Chọn kênh cho prompt hoặc đặt một kênh mặc định trong mục Kênh YouTube.')
            return
        try:
            self.controller.arm(prompt_id, channel_id,
                                rights_confirmed=True, upload_confirmed=True)
        except ValueError as error:
            self._notice(str(error))

    def _set_prompt_channel(self, prompt_id, channel_id):
        if self.controller.busy or prompt_id == self.controller.armed_prompt_id:
            self._notice('Tắt prompt và chờ tác vụ dừng trước khi đổi kênh.')
            self.refresh()
            return
        try:
            self.store.set_prompt_channel(prompt_id, channel_id)
        except ValueError as error:
            self._notice(str(error))
        self.refresh()

    def _delete(self, prompt_id):
        if self.controller.busy:
            return
        dialog = ConfirmDialog(
            title='Xóa prompt tự động hóa?',
            message='Bạn có chắc chắn muốn xóa mẫu quy trình này? Hành động này không thể hoàn tác.',
            confirm_text='Xóa',
            cancel_text='Hủy',
            is_danger=True,
            parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if prompt_id == self.controller.armed_prompt_id:
            self.controller.deactivate()
        self.store.delete_prompt(prompt_id)
        self.refresh()

    def _notice(self, message):
        manager = ToastManager.instance()
        if manager:
            manager.warning('Tự động hóa', message)
