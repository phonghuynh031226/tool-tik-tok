"""Reusable EmptyState component for placeholders and empty lists."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui import icons, tokens


class EmptyState(QWidget):
    """Centered placeholder displaying an icon, title, description, and optional action button."""

    def __init__(
        self,
        icon_name: str = "info",
        title: str = "Chưa có dữ liệu",
        description: str = "",
        action_button: Optional[QPushButton] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_XL, tokens.SPACE_2XL, tokens.SPACE_XL, tokens.SPACE_2XL)
        layout.setSpacing(tokens.SPACE_SM)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon
        icon_lbl = QLabel(self)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(icons.get_colored_icon(icon_name, tokens.TEXT_MUTED).pixmap(48, 48))
        layout.addWidget(icon_lbl)

        # Title
        title_lbl = QLabel(title, self)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(f"font-size: {tokens.FONT_SIZE_LG}px; font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(title_lbl)

        # Description
        if description:
            desc_lbl = QLabel(description, self)
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(f"font-size: {tokens.FONT_SIZE_SM}px; color: {tokens.TEXT_SECONDARY}; max-width: 400px;")
            layout.addWidget(desc_lbl)

        if action_button:
            layout.addSpacing(tokens.SPACE_SM)
            layout.addWidget(action_button, alignment=Qt.AlignmentFlag.AlignCenter)
