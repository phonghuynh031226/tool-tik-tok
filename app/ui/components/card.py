"""Reusable Card frame component for grouping sections."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)


class Card(QFrame):
    """Visual card container with rounded corners and distinct background."""

    def __init__(
        self,
        step_number: Optional[int] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        # Header section if title is provided
        if title:
            header_layout = QHBoxLayout()
            header_layout.setSpacing(10)

            if step_number is not None:
                badge = QLabel(str(step_number))
                badge.setProperty("class", "stepBadge")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                header_layout.addWidget(badge)

            title_box = QVBoxLayout()
            title_box.setSpacing(2)

            title_label = QLabel(title)
            title_label.setProperty("class", "stepTitle")
            title_box.addWidget(title_label)

            if subtitle:
                sub_label = QLabel(subtitle)
                sub_label.setProperty("class", "stepSubtitle")
                title_box.addWidget(sub_label)

            header_layout.addLayout(title_box)
            header_layout.addStretch()

            self.main_layout.addLayout(header_layout)

    def add_widget(self, widget: QWidget) -> None:
        self.main_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.main_layout.addLayout(layout)

