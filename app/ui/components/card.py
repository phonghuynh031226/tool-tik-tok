"""Reusable Card frame component for grouping sections."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from app.ui import icons, tokens
from app.ui import i18n as _i18n


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
                badge.setFixedSize(24, 24)
                badge.setStyleSheet(
                    f"background-color: {tokens.PRIMARY}; color: {tokens.TEXT_INVERTED}; "
                    f"border-radius: 12px; font-weight: {tokens.FONT_WEIGHT_BOLD}; border: none;"
                )
                header_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            elif icon:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(
                    icons.get_colored_icon(icon, tokens.PRIMARY).pixmap(22, 22)
                )
                header_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

            if title:
                title_box = QVBoxLayout()
                title_box.setSpacing(2)
                title_box.setContentsMargins(0, 0, 0, 0)

                title_label = _i18n.bind(QLabel(title), title)
                title_label.setProperty("class", "stepTitle")
                title_box.addWidget(title_label)

                if subtitle:
                    sub_label = _i18n.bind(QLabel(subtitle), subtitle)
                    sub_label.setProperty("class", "stepDesc")
                    sub_label.setWordWrap(True)
                    sub_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                    title_box.addWidget(sub_label)

                header_layout.addLayout(title_box, 1)

            header_layout.addStretch()

            if header_action:
                header_layout.addWidget(header_action, 0, Qt.AlignmentFlag.AlignTop)

            self.main_layout.addLayout(header_layout)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.main_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.main_layout.addLayout(layout)
