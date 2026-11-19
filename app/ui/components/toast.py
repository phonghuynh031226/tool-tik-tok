"""Non-blocking stacking Toast Notification system with system tray integration."""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from app.ui import icons, tokens
from app.ui.components.buttons import AppButton

DEFAULT_FALLBACK_TITLES = {
    "error": "Thông báo lỗi",
    "warning": "Cảnh báo tác vụ",
    "info": "Thông báo",
    "success": "Thành công",
}

DEFAULT_FALLBACK_MESSAGES = {
    "error": "Đã xảy ra lỗi trong quá trình xử lý. Vui lòng kiểm tra lại hoặc thử lại sau.",
    "warning": "Cảnh báo tác vụ. Vui lòng kiểm tra lại thông tin.",
    "info": "Thông báo từ hệ thống ứng dụng.",
    "success": "Thao tác đã được thực hiện thành công.",
}


class ToastNotification(QFrame):
    """A single floating, non-blocking toast alert."""

    def __init__(
        self,
        toast_type: str,  # 'success', 'info', 'warning', 'error'
        title: str,
        message: str = "",
        action_text: Optional[str] = None,
        action_callback: Optional[Callable[[], None]] = None,
        duration_ms: int = 4500,
        on_close: Optional[Callable[[ToastNotification], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.toast_type = toast_type
        self.on_close_cb = on_close
        self.setFixedWidth(360)

        # Sanitize title and message - ensure they are NEVER empty or placeholder dashes
        clean_title = (title or "").strip()
        if not clean_title or clean_title in ("—", "-", "--", "None"):
            clean_title = DEFAULT_FALLBACK_TITLES.get(toast_type, "Thông báo")

        clean_message = (message or "").strip()
        if not clean_message or clean_message in ("—", "-", "--", "None"):
            clean_message = DEFAULT_FALLBACK_MESSAGES.get(toast_type, "Thông báo từ hệ thống.")

        self.title_text = clean_title
        self.message_text = clean_message

        # Theme colors by type
        if toast_type == "success":
            accent = tokens.SUCCESS
            bg = tokens.BG_CARD
            border = tokens.SUCCESS_BORDER
            icon_name = "success"
        elif toast_type == "warning":
            accent = tokens.WARNING
            bg = tokens.BG_CARD
            border = tokens.WARNING_BORDER
            icon_name = "warning"
        elif toast_type == "error":
            accent = tokens.DANGER
            bg = tokens.BG_CARD
            border = tokens.DANGER_BORDER
            icon_name = "error"
        else:
            accent = tokens.INFO
            bg = tokens.BG_CARD
            border = tokens.INFO_BORDER
            icon_name = "info"

        self.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {bg};"
            f"  border: 1px solid {border};"
            f"  border-left: 4px solid {accent};"
            f"  border-radius: {tokens.RADIUS_MD}px;"
            f"}}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Status Icon
        icon_lbl = QLabel(self)
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        icon_lbl.setPixmap(icons.get_colored_icon(icon_name, accent).pixmap(20, 20))
        layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        # Content Box
        content_box = QVBoxLayout()
        content_box.setSpacing(4)
        content_box.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel(self.title_text, self)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet(
            f"font-size: {tokens.FONT_SIZE_BASE}px; font-weight: 700; color: {tokens.TEXT_PRIMARY}; border: none; background: transparent;"
        )
        content_box.addWidget(self.lbl_title)

        self.lbl_msg = QLabel(self.message_text, self)
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setStyleSheet(
            f"font-size: {tokens.FONT_SIZE_SM}px; color: {tokens.TEXT_SECONDARY}; border: none; background: transparent;"
        )
        content_box.addWidget(self.lbl_msg)

        if action_text and action_callback:
            btn_action = AppButton(action_text, variant="primary", height=28, parent=self)
            btn_action.clicked.connect(action_callback)
            btn_action.clicked.connect(self.close_toast)
            content_box.addWidget(btn_action, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(content_box, stretch=1)

        # Close button
        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(icons.get_colored_icon("close", tokens.TEXT_MUTED))
        self.btn_close.setIconSize(QSize(14, 14))
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {tokens.BG_INPUT_HOVER}; }}"
        )
        self.btn_close.clicked.connect(self.close_toast)
        layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignTop)

        # Auto-dismiss timer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.close_toast)
        if duration_ms > 0:
            self.timer.start(duration_ms)

    def enterEvent(self, event) -> None:
        """Pause dismissal while hovered."""
        if self.timer.isActive():
            self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Resume dismissal when pointer leaves."""
        self.timer.start(2000)
        super().leaveEvent(event)

    def close_toast(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
        if self.on_close_cb:
            self.on_close_cb(self)
        self.deleteLater()


class ToastManager(QObject):
    """Manages positioning, stacking, and dismissal of multiple active toasts pinned to bottom-right."""

    _instance: Optional[ToastManager] = None

    def __init__(self, parent_window: QWidget) -> None:
        super().__init__(parent_window)
        self.window = parent_window
        self.toasts: List[ToastNotification] = []
        ToastManager._instance = self
        if self.window is not None:
            self.window.installEventFilter(self)

    def eventFilter(self, watched, event: QEvent) -> bool:
        if watched == self.window and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.reposition()
        return super().eventFilter(watched, event)

    @classmethod
    def instance(cls) -> Optional[ToastManager]:
        from shiboken6 import isValid
        if cls._instance is not None and not isValid(cls._instance.window):
            cls._instance = None
        return cls._instance

    def success(self, title: str, message: str = "") -> ToastNotification:
        return self.show("success", title, message)

    def info(self, title: str, message: str = "") -> ToastNotification:
        return self.show("info", title, message)

    def warning(self, title: str, message: str = "") -> ToastNotification:
        return self.show("warning", title, message)

    def error(self, title: str, message: str = "") -> ToastNotification:
        return self.show("error", title, message)

    def show(
        self,
        toast_type: str,
        title: str,
        message: str = "",
        action_text: Optional[str] = None,
        action_callback: Optional[Callable[[], None]] = None,
        duration_ms: int = 4500,
    ) -> ToastNotification:
        toast = ToastNotification(
            toast_type=toast_type,
            title=title,
            message=message,
            action_text=action_text,
            action_callback=action_callback,
            duration_ms=duration_ms,
            on_close=self._on_toast_closed,
            parent=self.window,
        )
        self.toasts.append(toast)
        toast.ensurePolished()
        toast.adjustSize()
        toast.resize(toast.width(), max(toast.sizeHint().height(), toast.heightForWidth(toast.width())))
        toast.show()
        self.reposition()
        return toast

    def _on_toast_closed(self, toast: ToastNotification) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
            self.reposition()

    def reposition(self) -> None:
        """Reposition all toasts stacked at bottom-right of the main window."""
        from shiboken6 import isValid
        if not isValid(self.window):
            return
        self.toasts = [toast for toast in self.toasts if isValid(toast)]
        margin_right = 24
        margin_bottom = 24
        spacing = 10

        win_w = self.window.width()
        win_h = self.window.height()
        current_y = win_h - margin_bottom

        for toast in reversed(self.toasts):
            t_height = toast.height()
            current_y -= t_height
            toast_x = max(10, win_w - toast.width() - margin_right)
            toast.move(toast_x, max(10, current_y))
            toast.raise_()
            current_y -= spacing
