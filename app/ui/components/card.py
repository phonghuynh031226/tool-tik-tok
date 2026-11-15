"""Reusable Card frame component for grouping sections."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from app.ui import icons, tokens


class Card(QFrame):
    """Visual card container with rounded corners and distinct background."""

    def __init__(
        self,
        step_number: Optional[int] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        icon: Optional[str] = None,
        header_action: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(
            tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG
        )
        self.main_layout.setSpacing(tokens.SPACE_MD)

        # Header section if title or icon is provided
        if title or icon or step_number is not None:
            header_layout = QHBoxLayout()
            header_layout.setSpacing(tokens.SPACE_MD)

            if step_number is not None:
                badge = QLabel(str(step_number))
                badge.setProperty("class", "stepBadge")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                header_layout.addWidget(badge)
            elif icon:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(
                    icons.get_colored_icon(icon, tokens.PRIMARY).pixmap(22, 22)
                )
                header_layout.addWidget(icon_lbl)

            if title:
                title_box = QVBoxLayout()
                title_box.setSpacing(tokens.SPACE_XS)

                title_label = QLabel(title)
                title_label.setProperty("class", "stepTitle")
                title_box.addWidget(title_label)

                if subtitle:
                    sub_label = QLabel(subtitle)
                    sub_label.setProperty("class", "stepDesc")
                    title_box.addWidget(sub_label)

                header_layout.addLayout(title_box)

            header_layout.addStretch()

            if header_action:
                header_layout.addWidget(header_action)

            self.main_layout.addLayout(header_layout)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.main_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.main_layout.addLayout(layout)
