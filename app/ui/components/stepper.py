"""Stepper component for displaying workflow stages."""

from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.ui import i18n as _i18n
from app.ui import tokens
from app.ui.icons import get_icon


StepState = Literal["pending", "active", "done"]


class StepItemWidget(QFrame):
    """An individual step widget in the stepper."""

    clicked = Signal(int)

    def __init__(
        self,
        step_number: int,
        title: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.step_number = step_number
        self.title_text = title
        self._state: Optional[StepState] = None

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_compact = False
        self._init_ui()
        self.set_state("pending")

    def _init_ui(self) -> None:
        self.setObjectName("stepItem")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Circular indicator button/label
        self.lbl_circle = QLabel(str(self.step_number), self)
        self.lbl_circle.setObjectName("stepCircle")
        self.lbl_circle.setFixedSize(32, 32)
        self.lbl_circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_circle)

        # Info container (Title + Status text)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = _i18n.bind(QLabel(self.title_text, self), self.title_text)
        self.lbl_title.setObjectName("stepTitle")
        self.lbl_title.setStyleSheet("border: none; background: transparent;")
        info_layout.addWidget(self.lbl_title)

        self.lbl_status = _i18n.ui(QLabel("Chưa làm", self))
        self.lbl_status.setObjectName("stepStatus")
        self.lbl_status.setStyleSheet("border: none; background: transparent;")
        info_layout.addWidget(self.lbl_status)

        layout.addLayout(info_layout)

        self.setStyleSheet(f"""
            QFrame#stepItem {{
                background-color: {tokens.BG_CARD};
                border: 1px solid {tokens.BORDER_SUBTLE};
                border-radius: 8px;
            }}
            QFrame#stepItem:hover {{
                border-color: {tokens.BORDER_DEFAULT};
            }}
            QFrame#stepItem[stepState="active"] {{
                background-color: rgba(56, 189, 248, 0.12);
                border: 1.5px solid {tokens.COLOR_PRIMARY};
            }}
            QFrame#stepItem[stepState="done"] {{
                background-color: rgba(34, 197, 94, 0.08);
                border: 1px solid rgba(34, 197, 94, 0.3);
            }}
            QFrame#stepItem QLabel {{
                border: none;
                background: transparent;
            }}
            QLabel#stepCircle {{
                background-color: {tokens.BG_APP};
                color: {tokens.TEXT_MUTED};
                border: 1px solid {tokens.BORDER_SUBTLE};
                border-radius: 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QFrame#stepItem[stepState="active"] QLabel#stepCircle {{
                background-color: {tokens.COLOR_PRIMARY};
                color: #ffffff;
                border: none;
                font-size: 13px;
            }}
            QFrame#stepItem[stepState="done"] QLabel#stepCircle {{
                background-color: {tokens.COLOR_SUCCESS};
                color: #ffffff;
                border: none;
                font-size: 14px;
            }}
            QLabel#stepTitle {{
                color: {tokens.TEXT_MUTED};
                font-size: 13px;
                font-weight: 500;
                border: none;
                background: transparent;
            }}
            QFrame#stepItem[stepState="active"] QLabel#stepTitle {{
                color: {tokens.COLOR_PRIMARY};
                font-weight: 700;
            }}
            QFrame#stepItem[stepState="done"] QLabel#stepTitle {{
                color: {tokens.TEXT_PRIMARY};
                font-weight: 600;
            }}
            QLabel#stepStatus {{
                color: {tokens.TEXT_MUTED};
                font-size: 11px;
                border: none;
                background: transparent;
            }}
            QFrame#stepItem[stepState="active"] QLabel#stepStatus {{
                color: {tokens.COLOR_PRIMARY};
                font-weight: 600;
            }}
            QFrame#stepItem[stepState="done"] QLabel#stepStatus {{
                color: {tokens.COLOR_SUCCESS};
                font-weight: 500;
            }}
        """)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.clicked.emit(self.step_number)

    def set_compact(self, compact: bool) -> None:
        """Toggle compact mode: hide status label, reduce padding and circle size."""
        if self._is_compact == compact:
            return
        self._is_compact = compact
        self.lbl_status.setVisible(not compact)
        layout = self.layout()
        if isinstance(layout, QHBoxLayout):
            if compact:
                layout.setContentsMargins(8, 4, 8, 4)
                layout.setSpacing(6)
                self.lbl_circle.setFixedSize(24, 24)
            else:
                layout.setContentsMargins(12, 10, 12, 10)
                layout.setSpacing(12)
                self.lbl_circle.setFixedSize(32, 32)
        self.updateGeometry()

    def set_state(self, state: StepState) -> None:
        if self._state == state:
            return
        self._state = state
        self.setProperty("stepState", state)
        if state == "done":
            self.lbl_circle.setText("✓")
            _i18n.set_text(self.lbl_status, "Hoàn thành")
        elif state == "active":
            self.lbl_circle.setText(str(self.step_number))
            _i18n.set_text(self.lbl_status, "Đang làm")
        else:
            self.lbl_circle.setText(str(self.step_number))
            _i18n.set_text(self.lbl_status, "Chưa làm")

        self.style().unpolish(self)
        self.style().polish(self)
        for child in (self.lbl_circle, self.lbl_title, self.lbl_status):
            child.style().unpolish(child)
            child.style().polish(child)


class WorkflowStepper(QFrame):
    """Horizontal 3-step workflow indicator."""

    step_selected = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: transparent; border: none; }}"
        )
        self._items: dict[int, StepItemWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        steps = [
            (1, "Video"),
            (2, "Nội dung AI"),
            (3, "Đăng YouTube"),
        ]

        for step_num, title in steps:
            item = StepItemWidget(step_num, title, self)
            item.clicked.connect(self.step_selected.emit)
            self._items[step_num] = item
            layout.addWidget(item, stretch=1)

    def set_compact(self, compact: bool) -> None:
        """Set compact mode across all step items."""
        for item in self._items.values():
            item.set_compact(compact)
        self.updateGeometry()

    def set_step_state(self, step_number: int, state: StepState) -> None:
        if step_number in self._items:
            self._items[step_number].set_state(state)
        elif step_number == 4 and 3 in self._items:
            self._items[3].set_state(state)

    def get_step_state(self, step_number: int) -> StepState:
        if step_number in self._items:
            return self._items[step_number]._state
        elif step_number == 4 and 3 in self._items:
            return self._items[3]._state
        return "pending"
