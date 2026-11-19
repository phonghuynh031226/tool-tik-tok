"""Explicit bindings for application copy; never translate editable user content."""
from PySide6.QtCore import Qt
from app.ui.translations import ENGLISH

ITEM_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 701


def translate(source, language):
    if language != 'en':
        return source
    stripped = source.strip()
    translated = ENGLISH.get(stripped)
    if translated is None:
        return source
    return source[:len(source)-len(source.lstrip())] + translated + source[len(source.rstrip()):]


def language_for(widget):
    node = widget
    while node is not None:
        preferences = getattr(node, 'ui_preferences', None)
        if preferences is not None:
            return preferences.language
        node = node.parent()
    return 'vi'


def bind(widget, source, field='text', *, preserve_format=False):
    if not preserve_format:
        getattr(widget, '_ui_formats', {}).pop(field, None)
    bindings = getattr(widget, '_ui_copy', None)
    if bindings is None:
        bindings = widget._ui_copy = {}
    bindings[field] = source
    rendered = translate(source, language_for(widget))
    getattr(widget, 'set' + field[0].upper() + field[1:])(rendered)
    if not hasattr(widget, '_ui_rendered_copy'):
        widget._ui_rendered_copy = {}
    widget._ui_rendered_copy[field] = rendered
    return widget


def ui(widget):
    return bind(widget, widget.text())


def set_text(widget, source):
    bind(widget, source)


def placeholder(widget, source):
    bind(widget, source, 'placeholderText')


def tooltip(widget, source):
    bind(widget, source, 'toolTip')


def title(widget, source):
    bind(widget, source, 'windowTitle')


def add_item(widget, source, *args, **kwargs):
    widget.addItem(translate(source, language_for(widget)), *args, **kwargs)
    widget.setItemData(widget.count()-1, source, ITEM_SOURCE_ROLE)


def add_items(widget, sources):
    for source in sources:
        add_item(widget, source)


def headers(widget, sources):
    widget._ui_headers = list(sources)
    widget.setHorizontalHeaderLabels([translate(s, language_for(widget)) for s in sources])


def format_text(widget, template, *values, field='text'):
    if not hasattr(widget, '_ui_formats'):
        widget._ui_formats = {}
    widget._ui_formats[field] = (template, values)
    bind(widget, translate(template, language_for(widget)).format(*values), field, preserve_format=True)


def retranslate(widget, language):
    for field, (template, values) in list(getattr(widget, '_ui_formats', {}).items()):
        if getattr(widget, field)() != getattr(widget, '_ui_rendered_copy', {}).get(field):
            del widget._ui_formats[field]
            getattr(widget, '_ui_copy', {}).pop(field, None)
            continue
        bind(widget, translate(template, language).format(*values), field, preserve_format=True)
    for field, source in list(getattr(widget, '_ui_copy', {}).items()):
        previous = getattr(widget, '_ui_rendered_copy', {}).get(field)
        if getattr(widget, field)() != previous:
            # A data-driven setter replaced the authored UI copy. Leave it untouched.
            del widget._ui_copy[field]
            continue
        setter = getattr(widget, 'set' + field[0].upper() + field[1:])
        rendered = translate(source, language)
        if getattr(widget, field)() != rendered:
            setter(rendered)
        widget._ui_rendered_copy[field] = rendered
    if hasattr(widget, '_ui_headers'):
        for i, source in enumerate(widget._ui_headers):
            item = widget.horizontalHeaderItem(i)
            if item and item.text() != translate(source, language):
                item.setText(translate(source, language))
    from PySide6.QtWidgets import QComboBox
    if isinstance(widget, QComboBox):
        blocked = widget.blockSignals(True)
        try:
            for i in range(widget.count()):
                source = widget.itemData(i, ITEM_SOURCE_ROLE)
                if source is not None:
                    rendered = translate(source, language)
                    if widget.itemText(i) != rendered:
                        widget.setItemText(i, rendered)
        finally:
            widget.blockSignals(blocked)


def formatted(widget, template, *values):
    format_text(widget, template, *values)
    return widget
