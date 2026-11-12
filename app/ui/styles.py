"""Dark Mode Theme and Styling for TikTok YouTube Studio."""

DARK_THEME_QSS = """
/* Global defaults */
* {
    font-family: "Segoe UI", "SF Pro Display", -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #f4f4f5;
    outline: none;
}

QMainWindow, QWidget#centralWidget, QDialog {
    background-color: #0f1117;
}

/* Scroll areas */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* Sidebar styling */
#sidebar {
    background-color: #161822;
    border-right: 1px solid #232736;
    min-width: 230px;
    max-width: 250px;
}

#sidebarHeader {
    padding: 16px 12px;
}

#appLogoTitle {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
}

#appSubtitle {
    font-size: 11px;
    color: #94a3b8;
}

/* Sidebar nav buttons */
QPushButton.navBtn {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: #94a3b8;
    margin: 2px 8px;
}

QPushButton.navBtn:hover {
    background-color: #202434;
    color: #f1f5f9;
}

QPushButton.navBtn:checked, QPushButton.navBtn.active {
    background-color: #3b82f6;
    color: #ffffff;
    font-weight: 600;
}

/* Cards / Section Frames */
QFrame.card {
    background-color: #1a1d2b;
    border: 1px solid #272c3d;
    border-radius: 10px;
    padding: 16px;
}

QFrame.card:hover {
    border-color: #333a50;
}

/* Step Header in Card */
QLabel.stepBadge {
    background-color: #3b82f6;
    color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    border-radius: 12px;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    qproperty-alignment: AlignCenter;
}

QLabel.stepTitle {
    font-size: 15px;
    font-weight: 600;
    color: #ffffff;
}

QLabel.stepSubtitle {
    font-size: 12px;
    color: #94a3b8;
}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #12141e;
    border: 1px solid #2d3348;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f8fafc;
    selection-background-color: #3b82f6;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
    background-color: #151824;
}

QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background-color: #161822;
    color: #64748b;
    border-color: #232736;
}

/* Buttons */
QPushButton {
    background-color: #252a3d;
    border: 1px solid #343c56;
    border-radius: 8px;
    padding: 8px 16px;
    color: #f1f5f9;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #2e354d;
    border-color: #424c6c;
}

QPushButton:pressed {
    background-color: #1e2232;
}

QPushButton:disabled {
    background-color: #1a1d29;
    color: #64748b;
    border-color: #232736;
}

/* Primary Accent Button */
QPushButton.primaryBtn {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 600;
}

QPushButton.primaryBtn:hover {
    background-color: #1d4ed8;
    border-color: #60a5fa;
}

QPushButton.primaryBtn:pressed {
    background-color: #1e40af;
}

QPushButton.primaryBtn:disabled {
    background-color: #1e293b;
    border-color: #334155;
    color: #64748b;
}

/* Success Button */
QPushButton.successBtn {
    background-color: #059669;
    border: 1px solid #10b981;
    color: #ffffff;
    font-weight: 600;
}

QPushButton.successBtn:hover {
    background-color: #047857;
    border-color: #34d399;
}

/* Danger Button */
QPushButton.dangerBtn {
    background-color: #dc2626;
    border: 1px solid #ef4444;
    color: #ffffff;
    font-weight: 600;
}

QPushButton.dangerBtn:hover {
    background-color: #b91c1c;
}

/* Progress Bar */
QProgressBar {
    background-color: #12141e;
    border: 1px solid #2d3348;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
    border-radius: 5px;
}

/* Checkbox and Radio Buttons */
QCheckBox, QRadioButton {
    spacing: 8px;
    color: #e2e8f0;
    font-size: 13px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #12141e;
}

QRadioButton::indicator {
    border-radius: 9px;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #3b82f6;
}

QCheckBox::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
    image: url("assets/check.svg");
}

QRadioButton::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
}

/* Combo box drop-down */
QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #1a1d2b;
    border: 1px solid #333a50;
    border-radius: 6px;
    color: #f8fafc;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
    padding: 4px;
}

/* Labels */
QLabel.fieldLabel {
    font-size: 12px;
    font-weight: 600;
    color: #cbd5e1;
    margin-bottom: 2px;
}

QLabel.hintLabel {
    font-size: 11px;
    color: #94a3b8;
}

QLabel.charCounter {
    font-size: 11px;
    color: #94a3b8;
}

QLabel.charCounterWarn {
    font-size: 11px;
    font-weight: 600;
    color: #f59e0b;
}

QLabel.charCounterDanger {
    font-size: 11px;
    font-weight: 700;
    color: #ef4444;
}

/* Video Player controls */
#videoPlaceholder {
    background-color: #0b0c12;
    border: 1px solid #1f2331;
    border-radius: 8px;
    color: #64748b;
    font-size: 13px;
}

/* QSlider */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #272c3d;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background-color: #3b82f6;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #ffffff;
    border: 1px solid #3b82f6;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background-color: #93c5fd;
}

/* Custom Scrollbars */
QScrollBar:vertical {
    border: none;
    background-color: #0f1117;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #272c3d;
    min-height: 25px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3b425b;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Tables */
QTableWidget {
    background-color: #12141e;
    border: 1px solid #272c3d;
    border-radius: 8px;
    gridline-color: #202434;
    color: #f8fafc;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #1e2232;
}

QTableWidget::item:selected {
    background-color: #202842;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #1a1d2b;
    border: none;
    border-bottom: 1px solid #2d3348;
    color: #94a3b8;
    font-weight: 600;
    padding: 8px;
}
"""

