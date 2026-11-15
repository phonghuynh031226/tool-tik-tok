"""Reusable Badge components for displaying status indicators."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.contracts import JobStatus
from app.ui import icons, tokens


class StatusBadge(QFrame):
    """Visual pill badge representing a JobStatus or custom state with icon and text."""

    def __init__(
        self,
        status: Optional[JobStatus | str] = None,
        parent: Optional[QWidget] = None,
        badge_type: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setObjectName("statusBadgeIcon")
        self.lbl_icon.setStyleSheet("border: none; background: transparent;")

        self.lbl_text = QLabel(self)
        self.lbl_text.setObjectName("statusBadgeText")
        self.lbl_text.setStyleSheet("border: none; background: transparent; font-weight: 600; font-size: 11px;")

        layout.addWidget(self.lbl_icon)
        layout.addWidget(self.lbl_text)

        if status is not None:
            self.set_status(status, badge_type=badge_type)

    def set_status(self, status: JobStatus | str, badge_type: Optional[str] = None) -> None:
        """Update badge styling and text according to JobStatus or explicit badge_type."""
        status_val = status.value if isinstance(status, JobStatus) else str(status)

        if badge_type == "success":
            text = status_val
            bg = tokens.SUCCESS_BG
            fg = "#6ee7b7"
            border = tokens.SUCCESS_BORDER
            icon_name = "check"
        elif badge_type == "warning":
            text = status_val
            bg = tokens.WARNING_BG
            fg = "#fde68a"
            border = tokens.WARNING_BORDER
            icon_name = "clock"
        elif badge_type == "danger":
            text = status_val
            bg = tokens.DANGER_BG
            fg = "#fca5a5"
            border = tokens.DANGER_BORDER
            icon_name = "error"
        elif badge_type == "info":
            text = status_val
            bg = tokens.INFO_BG
            fg = "#7dd3fc"
            border = tokens.INFO_BORDER
            icon_name = "info"
        elif status_val == JobStatus.UPLOADED.value:
            text = "Đã xuất bản"
            bg = tokens.SUCCESS_BG
            fg = "#6ee7b7"
            border = tokens.SUCCESS_BORDER
            icon_name = "check"
        elif status_val in (JobStatus.CONTENT_READY.value, JobStatus.DOWNLOADED.value):
            text = "Nội dung sẵn sàng" if status_val == JobStatus.CONTENT_READY.value else "Đã tải video"
            bg = tokens.INFO_BG
            fg = "#7dd3fc"
            border = tokens.INFO_BORDER
            icon_name = "video" if status_val == JobStatus.DOWNLOADED.value else "sparkle"
        elif status_val in (JobStatus.UPLOADING.value, JobStatus.SCHEDULED.value):
            text = "Đang xử lý..."
            bg = tokens.WARNING_BG
            fg = "#fde68a"
            border = tokens.WARNING_BORDER
            icon_name = "clock"
        elif status_val == JobStatus.FAILED.value:
            text = "Thất bại"
            bg = tokens.DANGER_BG
            fg = "#fca5a5"
            border = tokens.DANGER_BORDER
            icon_name = "error"
        elif status_val == "DRY_RUN":
            text = "Chạy thử"
            bg = tokens.INFO_BG
            fg = "#93c5fd"
            border = tokens.INFO_BORDER
            icon_name = "flask"
        else:
            text = "Mới tạo" if status_val == JobStatus.NEW.value else status_val
            bg = tokens.BG_INPUT
            fg = tokens.TEXT_SECONDARY
            border = tokens.BORDER_DEFAULT
            icon_name = "info"

        self.setStyleSheet(f"""
            QFrame#statusBadge {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {tokens.RADIUS_SM}px;
            }}
            QFrame#statusBadge QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_text.setStyleSheet(f"color: {fg}; font-weight: 600; font-size: 11px; border: none; background: transparent;")
        self.lbl_text.setText(text)
        self.lbl_icon.setPixmap(icons.get_colored_icon(icon_name, fg).pixmap(14, 14))
        self.lbl_icon.setStyleSheet("border: none; background: transparent;")

    def text(self) -> str:
        """Return badge display text."""
        return self.lbl_text.text()
