"""Reusable Metric / StatCard component."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui import icons, tokens


class StatCard(QFrame):
    """Card displaying a single key metric with icon, value, and label."""

    def __init__(
        self,
        label: str = "",
        value: str = "",
        icon_name: Optional[str] = None,
        icon_color: str = tokens.PRIMARY,
        parent: Optional[QWidget] = None,
        title: Optional[str] = None,
        change_text: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "statCard")

        display_label = title if title is not None else label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_MD, tokens.SPACE_MD, tokens.SPACE_MD, tokens.SPACE_MD
        )
        layout.setSpacing(tokens.SPACE_MD)

        if icon_name:
            icon_lbl = QLabel(self)
            icon_lbl.setPixmap(icons.get_colored_icon(icon_name, icon_color).pixmap(24, 24))
            icon_lbl.setStyleSheet("background: transparent;")
            layout.addWidget(icon_lbl)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.lbl_value = QLabel(value, self)
        self.lbl_value.setProperty("class", "statValue")

        self.lbl_label = QLabel(display_label, self)
        self.lbl_label.setProperty("class", "statLabel")

        text_layout.addWidget(self.lbl_value)
        text_layout.addWidget(self.lbl_label)

        if change_text:
            self.lbl_change = QLabel(change_text, self)
            self.lbl_change.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED};")
            self.lbl_change.setWordWrap(True)
            text_layout.addWidget(self.lbl_change)

        layout.addLayout(text_layout)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        self.lbl_value.setText(value)
