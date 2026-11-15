"""Reusable Labeled Input field with integrated error and help hints."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from app.ui import tokens


class LabeledInput(QWidget):
    """Input field paired with a clear title label and optional helper hint."""

    def __init__(
        self,
        label: str,
        placeholder: str = "",
        hint: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_XS)

        # Header with label
        lbl_header = QLabel(label, self)
        lbl_header.setProperty("class", "fieldLabel")
        layout.addWidget(lbl_header)

        # Line Edit
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.edit)

        # Optional Hint
        self.lbl_hint: Optional[QLabel] = None
        if hint:
            self.lbl_hint = QLabel(hint, self)
            self.lbl_hint.setStyleSheet(f"font-size: {tokens.FONT_SIZE_XS}px; color: {tokens.TEXT_MUTED};")
            layout.addWidget(self.lbl_hint)

    @property
    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)
