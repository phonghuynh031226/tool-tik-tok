"""Reusable Button components with icon support and distinct styling variants."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton, QWidget

from app.ui import icons, tokens


class AppButton(QPushButton):
    """Modern button supporting primary, secondary, danger, and ghost variants.

    Automatically handles state-colored icons from QtAwesome.
    """

    def __init__(
        self,
        text: str = "",
        variant: str = "secondary",  # 'primary', 'secondary', 'danger', 'ghost'
        icon_name: Optional[str] = None,
        parent: Optional[QWidget] = None,
        height: int = tokens.HEIGHT_BTN_MD,
    ) -> None:
        super().__init__(text, parent)
        self.variant = variant
        self.icon_name = icon_name

        # Assign CSS class for QSS styling
        if variant == "primary":
            self.setProperty("class", "btnPrimary")
        elif variant == "danger":
            self.setProperty("class", "btnDanger")
        elif variant == "ghost":
            self.setProperty("class", "btnGhost")
        else:
            self.setProperty("class", "btnSecondary")

        self.setMinimumHeight(height)
        self.setIconSize(QSize(18, 18))

        if icon_name:
            self.set_app_icon(icon_name)

    def set_app_icon(self, icon_name: str) -> None:
        """Apply state-aware icon based on button variant."""
        self.icon_name = icon_name
        if self.variant == "primary":
            c_normal = tokens.TEXT_INVERTED
            c_hover = tokens.TEXT_INVERTED
            c_active = tokens.TEXT_INVERTED
        elif self.variant == "danger":
            c_normal = "#fca5a5"
            c_hover = tokens.TEXT_INVERTED
            c_active = tokens.TEXT_INVERTED
        else:
            c_normal = tokens.TEXT_SECONDARY
            c_hover = tokens.TEXT_PRIMARY
            c_active = tokens.PRIMARY

        icon = icons.get_icon(
            icon_name,
            color=c_normal,
            color_hover=c_hover,
            color_active=c_active,
            color_disabled=tokens.TEXT_MUTED,
        )
        self.setIcon(icon)

    def set_icon_name(self, icon_name: str) -> None:
        """Alias for set_app_icon."""
        self.set_app_icon(icon_name)
