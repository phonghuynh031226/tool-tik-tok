from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def make_window(qtbot, services=None):
    services = services or ServiceContainer.create_fake()
    window = MainWindow(services)
    qtbot.addWidget(window)
    return window


def test_light_theme_applies_immediately_and_returns_to_dark(qtbot):
    window = make_window(qtbot)
    window.show()
    original = window.sidebar.palette().color(QPalette.ColorRole.Window).lightness()
    page = window.page_settings
    page.combo_theme.setCurrentIndex(page.combo_theme.findData('light'))
    qtbot.waitUntil(lambda: window.sidebar.palette().color(QPalette.ColorRole.Window).lightness() > 200)
    assert window.services.settings.get('ui_theme') == 'light'
    page.combo_theme.setCurrentIndex(page.combo_theme.findData('dark'))
    qtbot.waitUntil(lambda: window.sidebar.palette().color(QPalette.ColorRole.Window).lightness() == original)


def test_english_updates_navigation_settings_and_preserves_user_inputs(qtbot):
    window = make_window(qtbot)
    page = window.page_settings
    page.edit_prompt.setPlainText('Tổng quan — nội dung của tôi')
    page.combo_lang.setCurrentIndex(page.combo_lang.findData('en'))
    assert window.nav_group.button(0).text().strip() == 'Overview'
    assert page.btn_save_key.text() == 'Save key'
    assert page.edit_prompt.toPlainText() == 'Tổng quan — nội dung của tôi'
    assert page.combo_theme.currentData() == 'dark'
    page.combo_lang.setCurrentIndex(page.combo_lang.findData('vi'))
    assert window.nav_group.button(0).text().strip() == 'Tổng quan'
    assert page.btn_save_key.text() == 'Lưu khóa'


def test_preferences_are_restored_on_reopen_without_changing_combo_data(qtbot):
    services = ServiceContainer.create_fake()
    services.settings.set('ui_language', 'en')
    services.settings.set('ui_theme', 'light')
    window = make_window(qtbot, services)
    assert window.page_settings.combo_theme.currentData() == 'light'
    assert window.page_settings.combo_lang.currentData() == 'en'
    assert window.nav_group.button(4).text().strip() == 'Settings'
    assert '#f3f6fb' in window.styleSheet()


def test_language_change_keeps_history_title_and_model_identifiers(qtbot):
    window = make_window(qtbot)
    page = window.page_settings
    model = page.combo_gemini_model.currentData()
    window.page_history.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem
    window.page_history.table.setItem(0, 0, QTableWidgetItem('Tổng quan'))
    page.combo_lang.setCurrentIndex(page.combo_lang.findData('en'))
    assert window.page_history.table.item(0, 0).text() == 'Tổng quan'
    assert window.page_history.table.horizontalHeaderItem(0).text() == 'Video title'
    assert page.combo_gemini_model.currentData() == model


def test_new_dialog_uses_preferences_and_preserves_prompt_text(qtbot):
    from app.core.automation import AutomationStore
    from app.ui.pages.automation_page import AddPromptDialog
    window = make_window(qtbot)
    page = window.page_settings
    page.combo_lang.setCurrentIndex(page.combo_lang.findData('en'))
    page.combo_theme.setCurrentIndex(page.combo_theme.findData('light'))
    dialog = AddPromptDialog(window.services, AutomationStore(':memory:'), window)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: '#ffffff' in dialog.styleSheet())
    assert dialog.windowTitle() == 'Add automation prompt'
    assert any(label.text() == 'Add an automation workflow' for label in dialog.findChildren(QLabel))
    assert 'background-color: #171a27' not in dialog.styleSheet()


def test_dynamic_copy_changes_language_without_translating_inserted_values(qtbot):
    from app.ui import i18n
    window = make_window(qtbot)
    label = QLabel(window)
    i18n.format_text(label, 'Tiêu đề: {0}', 'Tổng quan')
    window.page_settings.combo_lang.setCurrentIndex(1)
    assert label.text() == 'Title: Tổng quan'
    window.page_settings.combo_lang.setCurrentIndex(0)
    assert label.text() == 'Tiêu đề: Tổng quan'


def test_collapsed_sidebar_and_late_status_changes_follow_language(qtbot):
    from app.ui.components.badge import StatusBadge
    window = make_window(qtbot)
    window.page_settings.combo_lang.setCurrentIndex(1)
    window._sidebar_collapsed = True
    window._update_sidebar_state(True)
    assert window.nav_group.button(0).text() == ''
    assert window.nav_group.button(0).toolTip() == 'Overview'
    window._sidebar_collapsed = False
    window._update_sidebar_state(False)
    assert window.nav_group.button(0).text().strip() == 'Overview'
    badge = StatusBadge('Đã công khai', window, badge_type='success')
    assert badge.text() == 'Published'
    badge.set_status('Cần kiểm tra', badge_type='warning')
    assert badge.text() == 'Needs checking'
