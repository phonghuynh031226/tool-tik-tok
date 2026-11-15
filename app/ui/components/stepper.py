"""Stepper component for displaying workflow stages."""

from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

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
        self._state: StepState = "pending"

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._init_ui()
        self.set_state("pending")

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Circular indicator button/label
        self.lbl_circle = QLabel(str(self.step_number), self)
        self.lbl_circle.setFixedSize(32, 32)
        self.lbl_circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_circle)

        # Info container (Title + Status text)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel(self.title_text, self)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        info_layout.addWidget(self.lbl_title)

        self.lbl_status = QLabel("Chưa làm", self)
        self.lbl_status.setStyleSheet("font-size: 11px;")
        info_layout.addWidget(self.lbl_status)

        layout.addLayout(info_layout)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.clicked.emit(self.step_number)

    def set_state(self, state: StepState) -> None:
        self._state = state
        if state == "done":
            self.lbl_circle.setText("✓")
            self.lbl_circle.setStyleSheet(
                f"background-color: {tokens.COLOR_SUCCESS}; color: #ffffff; "
                f"border-radius: 16px; font-weight: bold; font-size: 14px;"
            )
            self.lbl_title.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
            self.lbl_status.setText("Hoàn thành")
            self.lbl_status.setStyleSheet(f"color: {tokens.COLOR_SUCCESS}; font-size: 11px; font-weight: 500;")
            self.setStyleSheet(
                f"QFrame {{ background-color: rgba(34, 197, 94, 0.08); "
                f"border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 8px; }}"
                f"QFrame:hover {{ background-color: rgba(34, 197, 94, 0.14); }}"
            )
        elif state == "active":
            self.lbl_circle.setText(str(self.step_number))
            self.lbl_circle.setStyleSheet(
                f"background-color: {tokens.COLOR_PRIMARY}; color: #ffffff; "
                f"border-radius: 16px; font-weight: bold; font-size: 13px;"
            )
            self.lbl_title.setStyleSheet(f"color: {tokens.COLOR_PRIMARY}; font-size: 13px; font-weight: 700;")
            self.lbl_status.setText("Đang làm")
            self.lbl_status.setStyleSheet(f"color: {tokens.COLOR_PRIMARY}; font-size: 11px; font-weight: 600;")
            self.setStyleSheet(
                f"QFrame {{ background-color: rgba(56, 189, 248, 0.12); "
                f"border: 1.5px solid {tokens.COLOR_PRIMARY}; border-radius: 8px; }}"
                f"QFrame:hover {{ background-color: rgba(56, 189, 248, 0.18); }}"
            )
        else:  # pending
            self.lbl_circle.setText(str(self.step_number))
            self.lbl_circle.setStyleSheet(
                f"background-color: {tokens.BG_APP}; color: {tokens.TEXT_MUTED}; "
                f"border: 1px solid {tokens.BORDER_SUBTLE}; border-radius: 16px; font-size: 12px;"
            )
            self.lbl_title.setStyleSheet(f"color: {tokens.TEXT_MUTED}; font-size: 13px; font-weight: 500;")
            self.lbl_status.setText("Chưa làm")
            self.lbl_status.setStyleSheet(f"color: {tokens.TEXT_MUTED}; font-size: 11px;")
            self.setStyleSheet(
                f"QFrame {{ background-color: {tokens.BG_CARD}; "
                f"border: 1px solid {tokens.BORDER_SUBTLE}; border-radius: 8px; }}"
                f"QFrame:hover {{ border-color: {tokens.BORDER_DEFAULT}; }}"
            )


class WorkflowStepper(QFrame):
    """Horizontal 4-step workflow indicator."""

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
            (1, "Nguồn Video"),
            (2, "Xem trước"),
            (3, "Tối ưu AI"),
            (4, "Xuất bản YouTube"),
        ]

        for step_num, title in steps:
            item = StepItemWidget(step_num, title, self)
            item.clicked.connect(self.step_selected.emit)
            self._items[step_num] = item
            layout.addWidget(item, stretch=1)

    def set_step_state(self, step_number: int, state: StepState) -> None:
        if step_number in self._items:
            self._items[step_number].set_state(state)

    def get_step_state(self, step_number: int) -> StepState:
        if step_number in self._items:
            return self._items[step_number]._state
        return "pending"
