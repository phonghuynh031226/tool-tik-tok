"""Reusable Labeled Input field with integrated error and help hints."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

from app.ui import tokens


class MultiLineTagEdit(QPlainTextEdit):
    """Multi-line text editor for tags/hashtags, showing 2-3 lines starting from the beginning."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setMinimumHeight(52)
        self.setMaximumHeight(76)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {tokens.BG_INPUT};
                color: {tokens.TEXT_PRIMARY};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: {tokens.RADIUS_MD}px;
                padding: 6px 8px;
                font-size: 13px;
            }}
            QPlainTextEdit:hover {{
                border-color: {tokens.BORDER_HOVER};
            }}
            QPlainTextEdit:focus {{
                border-color: {tokens.BORDER_FOCUS};
            }}
        """)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        tc = self.textCursor()
        tc.setPosition(0)
        self.setTextCursor(tc)


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
