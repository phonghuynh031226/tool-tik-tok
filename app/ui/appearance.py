"""Live, per-window appearance preferences, including child dialogs and inline styles."""
import re
from shiboken6 import isValid
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from app.ui import tokens
from app.ui.styles import DARK_THEME_QSS
from app.ui.i18n import retranslate

LIGHT_COLORS = {
    tokens.BG_APP.lower(): '#f3f6fb', tokens.BG_SIDEBAR.lower(): '#ffffff',
    tokens.BG_CARD.lower(): '#ffffff', tokens.BG_CARD_HOVER.lower(): '#edf2f8',
    tokens.BG_CARD_ACTIVE.lower(): '#dce8fa', tokens.BG_INPUT.lower(): '#f8fafc',
    tokens.BG_INPUT_HOVER.lower(): '#edf2f8', tokens.BG_INPUT_FOCUS.lower(): '#ffffff',
    tokens.BG_HEADER.lower(): '#eaf0f8', tokens.BG_MODAL.lower(): '#ffffff',
    tokens.BORDER_SUBTLE.lower(): '#e2e8f0', tokens.BORDER_DEFAULT.lower(): '#cbd5e1',
    tokens.BORDER_HOVER.lower(): '#94a3b8', tokens.TEXT_PRIMARY.lower(): '#172033',
    tokens.TEXT_SECONDARY.lower(): '#475569', tokens.TEXT_MUTED.lower(): '#52647a',
    '#0e1424': '#eaf0f8', '#111827': '#f1f5f9', '#1f2937': '#e2e8f0',
    '#1e293b': '#e2e8f0', '#0f172a': '#f8fafc', '#161925': '#ffffff',
    '#12141e': '#f8fafc', '#1e2235': '#eaf0f8', '#1e2233': '#eaf0f8',
    '#0b1220': '#f8fafc',
}
COLOR = re.compile(r'#[0-9a-fA-F]{6}\b')


def light_stylesheet(source):
    # Preserve white text on filled action buttons/status badges; convert page headings.
    def rule(match):
        text = match.group(0)
        background = re.search(r'background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})', text)
        filled = background and background[1].lower() not in LIGHT_COLORS and background[1].lower() != '#ffffff'
        def color(m):
            old = m[0].lower()
            if old == '#ffffff':
                return '#ffffff' if filled else '#172033'
            return LIGHT_COLORS.get(old, m[0])
        return COLOR.sub(color, text)
    return re.sub(r'[^{}]*\{[^{}]*\}|[^{}]+$', rule, source)


class UiPreferences(QObject):
    def __init__(self, window, settings):
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.language = 'vi'
        self.theme = 'dark'
        self._refresh_queued = False
        QApplication.instance().installEventFilter(self)

    def apply(self):
        self.language = 'en' if self.settings.get('ui_language', 'vi') == 'en' else 'vi'
        self.theme = 'light' if self.settings.get('ui_theme', 'dark') == 'light' else 'dark'
        qss = light_stylesheet(DARK_THEME_QSS) if self.theme == 'light' else DARK_THEME_QSS
        if self.window.styleSheet() != qss:
            self.window.setStyleSheet(qss)
        for widget in [self.window] + self.window.findChildren(QWidget):
            self._apply_widget(widget)
        self.window._update_sidebar_state(self.window._sidebar_collapsed)

    def _apply_widget(self, widget):
        if widget is not self.window:
            current = widget.styleSheet()
            previous = getattr(widget, '_ui_rendered_style', None)
            if current != previous:
                widget._ui_dark_style = current
            source = getattr(widget, '_ui_dark_style', current)
            rendered = light_stylesheet(source) if self.theme == 'light' else source
            widget._ui_rendered_style = rendered
            if current != rendered:
                widget.setStyleSheet(rendered)
        retranslate(widget, self.language)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.PolishRequest, QEvent.Type.Show, QEvent.Type.StyleChange, QEvent.Type.LayoutRequest) and isinstance(obj, QWidget):
            node = obj
            while node is not None and node is not self.window:
                node = node.parent()
            if node is self.window and not self._refresh_queued:
                # Do not retain event widgets: Qt can emit StyleChange while the
                # derived Python wrapper is still being constructed.
                self._refresh_queued = True
                QTimer.singleShot(0, self._refresh_children)
        return False

    def _refresh_children(self):
        self._refresh_queued = False
        if isValid(self.window):
            for widget in [self.window] + self.window.findChildren(QWidget):
                self._apply_widget(widget)
