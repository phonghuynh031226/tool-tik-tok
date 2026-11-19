from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def test_set_default_model_applies_to_pages_and_survives_transient_choice(qtbot):
    services=ServiceContainer.create_fake()
    services.generator.list_models=lambda: ['fake-gemini-dev','fake-gemini-other']
    window=MainWindow(services)
    qtbot.addWidget(window)
    page=window.page_settings
    page.combo_gemini_model.setCurrentIndex(1)
    chosen=page.combo_gemini_model.currentData()
    assert chosen is not None
    page.btn_default_model.click()
    assert services.settings.get('gemini_default_model')==chosen
    assert window.page_dashboard.combo_model.currentData()==chosen
    assert window.page_tools.combo_model.currentData()==chosen
    assert chosen in page.lbl_default_model.text()
    window.page_dashboard.combo_model.setCurrentIndex(0)
    assert services.settings.get('gemini_default_model')==chosen
    reopened=MainWindow(services)
    qtbot.addWidget(reopened)
    assert reopened.page_dashboard.combo_model.currentData()==chosen
    assert reopened.page_settings.combo_gemini_model.currentData()==chosen


def test_default_preference_is_not_overwritten_by_runtime_fallback(qtbot):
    services=ServiceContainer.create_fake()
    preferred=services.generator.list_models()[0]
    services.settings.set('gemini_default_model',preferred)
    window=MainWindow(services)
    qtbot.addWidget(window)
    services.gemini_selection.changed.emit('available-fallback','Fallback notice')
    assert services.settings.get('gemini_default_model')==preferred
    assert preferred in window.page_settings.lbl_default_model.text()
