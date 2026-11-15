"""Dark Mode Theme and Styling for TikTok YouTube Studio.

Built completely upon design tokens from app.ui.tokens.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.ui import tokens

DARK_THEME_QSS = f"""
/* Global base settings */
QWidget {{
    font-family: {tokens.FONT_FALLBACKS};
    font-size: {tokens.FONT_SIZE_BASE}px;
    color: {tokens.TEXT_PRIMARY};
    background-color: transparent;
    selection-background-color: {tokens.PRIMARY};
    selection-color: {tokens.TEXT_INVERTED};
}}

/* Prevent QFrame stylesheet rules from leaking borders onto child QLabels */
QLabel {{
    border: none;
    background-color: transparent;
}}

QFrame.card QLabel {{
    border: none;
    background-color: transparent;
}}

QFrame.statCard QLabel {{
    border: none;
    background-color: transparent;
}}

QMainWindow, QWidget#centralWidget, QDialog {{
    background-color: {tokens.BG_APP};
}}

/* Scroll Areas */
QScrollArea {{
    background-color: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* Sidebar styling */
#sidebar {{
    background-color: {tokens.BG_SIDEBAR};
    border-right: 1px solid {tokens.BORDER_SUBTLE};
}}

#sidebarHeader {{
    padding: {tokens.SPACE_LG}px {tokens.SPACE_MD}px {tokens.SPACE_MD}px {tokens.SPACE_MD}px;
}}

#appLogoTitle {{
    font-size: {tokens.FONT_SIZE_XL}px;
    font-weight: {tokens.FONT_WEIGHT_BOLD};
    color: {tokens.TEXT_INVERTED};
}}

#appSubtitle {{
    font-size: {tokens.FONT_SIZE_SM}px;
    color: {tokens.TEXT_SECONDARY};
}}

#sidebarFooter {{
    padding: {tokens.SPACE_MD}px;
    border-top: 1px solid {tokens.BORDER_SUBTLE};
    background-color: {tokens.BG_SIDEBAR};
}}

/* Sidebar navigation buttons */
QPushButton.navBtn {{
    background-color: transparent;
    border: none;
    border-radius: {tokens.RADIUS_MD}px;
    padding: 10px 14px;
    text-align: left;
    font-size: {tokens.FONT_SIZE_BASE}px;
    font-weight: {tokens.FONT_WEIGHT_MEDIUM};
    color: {tokens.TEXT_SECONDARY};
    margin: 2px {tokens.SPACE_SM}px;
}}

QPushButton.navBtn:hover {{
    background-color: {tokens.BG_INPUT_HOVER};
    color: {tokens.TEXT_PRIMARY};
}}

QPushButton.navBtn:checked, QPushButton.navBtn.active {{
    background-color: {tokens.PRIMARY};
    color: {tokens.TEXT_INVERTED};
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
}}

QPushButton.navBtnCollapsed {{
    background-color: transparent;
    border: none;
    border-radius: {tokens.RADIUS_MD}px;
    padding: 10px 0px;
    text-align: center;
    margin: 2px {tokens.SPACE_SM}px;
}}

QPushButton.navBtnCollapsed:hover {{
    background-color: {tokens.BG_INPUT_HOVER};
}}

QPushButton.navBtnCollapsed:checked {{
    background-color: {tokens.PRIMARY};
}}

/* Cards & Containers */
QFrame.card {{
    background-color: {tokens.BG_CARD};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_LG}px;
    padding: {tokens.SPACE_LG}px;
}}

QFrame.card:hover {{
    border-color: {tokens.BORDER_HOVER};
}}

/* Stat Card */
QFrame.statCard {{
    background-color: {tokens.BG_CARD};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_MD}px;
    padding: {tokens.SPACE_MD}px;
}}

QLabel.statValue {{
    font-size: {tokens.FONT_SIZE_2XL}px;
    font-weight: {tokens.FONT_WEIGHT_BOLD};
    color: {tokens.TEXT_PRIMARY};
}}

QLabel.statLabel {{
    font-size: {tokens.FONT_SIZE_SM}px;
    color: {tokens.TEXT_SECONDARY};
    font-weight: {tokens.FONT_WEIGHT_MEDIUM};
}}

/* Step badges and titles */
QLabel.stepBadge {{
    background-color: {tokens.PRIMARY};
    color: {tokens.TEXT_INVERTED};
    font-weight: {tokens.FONT_WEIGHT_BOLD};
    font-size: {tokens.FONT_SIZE_SM}px;
    border-radius: 12px;
    border: none;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    qproperty-alignment: AlignCenter;
}}

QLabel.stepTitle {{
    font-size: {tokens.FONT_SIZE_LG}px;
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
    color: {tokens.TEXT_PRIMARY};
    border: none;
    background-color: transparent;
}}

QLabel.stepDesc {{
    font-size: {tokens.FONT_SIZE_SM}px;
    color: {tokens.TEXT_SECONDARY};
    border: none;
    background-color: transparent;
}}

/* Buttons */
QPushButton {{
    border-radius: {tokens.RADIUS_MD}px;
    padding: 8px 16px;
    font-weight: {tokens.FONT_WEIGHT_MEDIUM};
    font-size: {tokens.FONT_SIZE_BASE}px;
    border: 1px solid transparent;
    outline: none;
}}

/* Primary Button */
QPushButton.btnPrimary, QPushButton.primaryBtn {{
    background-color: {tokens.PRIMARY};
    color: {tokens.TEXT_INVERTED};
    border: none;
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
}}

QPushButton.btnPrimary:hover, QPushButton.primaryBtn:hover {{
    background-color: {tokens.PRIMARY_HOVER};
}}

QPushButton.btnPrimary:pressed, QPushButton.primaryBtn:pressed {{
    background-color: {tokens.PRIMARY_ACTIVE};
}}

QPushButton.btnPrimary:disabled, QPushButton.primaryBtn:disabled {{
    background-color: {tokens.BORDER_DEFAULT};
    color: {tokens.TEXT_MUTED};
}}

/* Secondary Button */
QPushButton.btnSecondary, QPushButton.secondaryBtn {{
    background-color: {tokens.BG_INPUT};
    color: {tokens.TEXT_PRIMARY};
    border: 1px solid {tokens.BORDER_DEFAULT};
}}

QPushButton.btnSecondary:hover, QPushButton.secondaryBtn:hover {{
    background-color: {tokens.BG_INPUT_HOVER};
    border-color: {tokens.BORDER_HOVER};
}}

QPushButton.btnSecondary:pressed, QPushButton.secondaryBtn:pressed {{
    background-color: {tokens.BG_INPUT_FOCUS};
}}

QPushButton.btnSecondary:disabled, QPushButton.secondaryBtn:disabled {{
    background-color: {tokens.BG_APP};
    color: {tokens.TEXT_MUTED};
    border-color: {tokens.BORDER_SUBTLE};
}}

/* Danger Button */
QPushButton.btnDanger, QPushButton.dangerBtn {{
    background-color: {tokens.DANGER_BG};
    color: #fca5a5;
    border: 1px solid {tokens.DANGER_BORDER};
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
}}

QPushButton.btnDanger:hover, QPushButton.dangerBtn:hover {{
    background-color: {tokens.DANGER_BORDER};
    color: {tokens.TEXT_INVERTED};
}}

QPushButton.btnDanger:pressed, QPushButton.dangerBtn:pressed {{
    background-color: {tokens.DANGER_HOVER};
}}

/* Ghost Button */
QPushButton.btnGhost {{
    background-color: transparent;
    color: {tokens.TEXT_SECONDARY};
    border: none;
}}

QPushButton.btnGhost:hover {{
    background-color: {tokens.BG_INPUT_HOVER};
    color: {tokens.TEXT_PRIMARY};
}}

/* Input controls */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {tokens.BG_INPUT};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 8px 12px;
    color: {tokens.TEXT_PRIMARY};
    font-size: {tokens.FONT_SIZE_BASE}px;
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: {tokens.BORDER_HOVER};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {tokens.BORDER_FOCUS};
    background-color: {tokens.BG_INPUT_FOCUS};
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {tokens.BG_APP};
    color: {tokens.TEXT_MUTED};
    border-color: {tokens.BORDER_SUBTLE};
}}

QLabel.fieldLabel {{
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
    color: {tokens.TEXT_SECONDARY};
    font-size: {tokens.FONT_SIZE_SM}px;
    margin-bottom: 2px;
}}

/* ComboBox */
QComboBox {{
    background-color: {tokens.BG_INPUT};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 8px 12px;
    color: {tokens.TEXT_PRIMARY};
    min-height: 22px;
}}

QComboBox:hover {{
    border-color: {tokens.BORDER_HOVER};
}}

QComboBox:focus {{
    border-color: {tokens.BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

QComboBox QAbstractItemView {{
    background-color: {tokens.BG_CARD};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 4px;
    color: {tokens.TEXT_PRIMARY};
    selection-background-color: {tokens.PRIMARY};
    selection-color: {tokens.TEXT_INVERTED};
}}

/* CheckBoxes & RadioButtons */
QCheckBox, QRadioButton {{
    color: {tokens.TEXT_PRIMARY};
    spacing: 8px;
    font-size: {tokens.FONT_SIZE_BASE}px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_SM}px;
    background-color: {tokens.BG_INPUT};
}}

QCheckBox::indicator:hover {{
    border-color: {tokens.PRIMARY};
}}

QCheckBox::indicator:checked {{
    background-color: {tokens.PRIMARY};
    border-color: {tokens.PRIMARY};
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: 9px;
    background-color: {tokens.BG_INPUT};
}}

QRadioButton::indicator:hover {{
    border-color: {tokens.PRIMARY};
}}

QRadioButton::indicator:checked {{
    background-color: {tokens.PRIMARY};
    border-color: {tokens.PRIMARY};
}}

/* Badges */
QLabel.badge {{
    border-radius: {tokens.RADIUS_SM}px;
    padding: 3px 8px;
    font-size: {tokens.FONT_SIZE_SM}px;
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
}}

QLabel.badgeSuccess {{
    background-color: {tokens.SUCCESS_BG};
    color: #6ee7b7;
    border: 1px solid {tokens.SUCCESS_BORDER};
}}

QLabel.badgeWarning {{
    background-color: {tokens.WARNING_BG};
    color: #fde68a;
    border: 1px solid {tokens.WARNING_BORDER};
}}

QLabel.badgeDanger {{
    background-color: {tokens.DANGER_BG};
    color: #fca5a5;
    border: 1px solid {tokens.DANGER_BORDER};
}}

QLabel.badgeInfo {{
    background-color: {tokens.INFO_BG};
    color: #7dd3fc;
    border: 1px solid {tokens.INFO_BORDER};
}}

QLabel.badgeMuted {{
    background-color: {tokens.BG_INPUT};
    color: {tokens.TEXT_SECONDARY};
    border: 1px solid {tokens.BORDER_DEFAULT};
}}

/* Progress Bar */
QProgressBar {{
    background-color: {tokens.BG_INPUT};
    border: 1px solid {tokens.BORDER_SUBTLE};
    border-radius: {tokens.RADIUS_SM}px;
    height: 8px;
    text-align: right;
}}

QProgressBar::chunk {{
    background-color: {tokens.PRIMARY};
    border-radius: {tokens.RADIUS_SM}px;
}}

/* Tables */
QTableWidget, QTableView {{
    background-color: {tokens.BG_CARD};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_MD}px;
    gridline-color: {tokens.BORDER_SUBTLE};
    color: {tokens.TEXT_PRIMARY};
}}

QTableWidget::item, QTableView::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {tokens.BORDER_SUBTLE};
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {tokens.PRIMARY_BG};
    color: {tokens.TEXT_INVERTED};
}}

QHeaderView::section {{
    background-color: {tokens.BG_HEADER};
    color: {tokens.TEXT_SECONDARY};
    font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
    font-size: {tokens.FONT_SIZE_SM}px;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid {tokens.BORDER_DEFAULT};
}}

/* Modern Thin Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {tokens.BORDER_DEFAULT};
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {tokens.BORDER_HOVER};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px;
}}

QScrollBar::handle:horizontal {{
    background: {tokens.BORDER_DEFAULT};
    min-width: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {tokens.BORDER_HOVER};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ToolTips */
QToolTip {{
    background-color: {tokens.BG_MODAL};
    color: {tokens.TEXT_PRIMARY};
    border: 1px solid {tokens.BORDER_DEFAULT};
    border-radius: {tokens.RADIUS_SM}px;
    padding: 6px 10px;
    font-size: {tokens.FONT_SIZE_SM}px;
}}
"""


def apply_app_theme(app: QApplication) -> None:
    """Apply standard Segoe UI application font and dark stylesheet."""
    font = QFont(tokens.FONT_FAMILY, tokens.FONT_SIZE_MD)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    app.setStyleSheet(DARK_THEME_QSS)
