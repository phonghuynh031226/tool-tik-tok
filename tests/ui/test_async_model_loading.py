"""Regression coverage for nonblocking model catalog discovery."""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QMessageBox

from app.services.fakes import FakeSettingsStore
from app.ui.main_window import MainWindow
from app.ui.model_loading import populate_models
from app.ui.services import ServiceContainer


@pytest.mark.background_tasks
def test_window_initializes_while_model_catalog_is_waiting(qtbot):
    release = threading.Event()
    calls = []
    timed_out = []

    class WaitingGenerator:
        def list_models(self):
            calls.append(threading.get_ident())
            if not release.wait(5):
                timed_out.append(True)
            return ["gemini-2.5-flash-lite"]

    services = ServiceContainer.create_fake()
    services.generator = WaitingGenerator()
    services.settings.set("gemini_model", "gemini-2.5-flash-lite")
    try:
        window = MainWindow(services)
        qtbot.addWidget(window)
        qtbot.waitUntil(lambda: len(calls) == 3)
        assert not timed_out
        assert all(thread_id != threading.get_ident() for thread_id in calls)
        combos = [window.page_dashboard.combo_model, window.page_tools.combo_model,
                  window.page_settings.combo_gemini_model]
        assert all(not combo.isEnabled() for combo in combos)
        assert all(combo.currentData() == "gemini-2.5-flash-lite" for combo in combos)
    finally:
        release.set()
    qtbot.waitUntil(lambda: all(combo.isEnabled() for combo in combos))
    assert all(combo.currentData() == "gemini-2.5-flash-lite" for combo in combos)


@pytest.mark.parametrize("fails", [False, True])
def test_loaded_catalog_preserves_fallback_notice_and_does_not_emit_selection_changes(qtbot, monkeypatch, fails):
    class Generator:
        def list_models(self):
            if fails:
                raise RuntimeError("catalog unavailable")
            return ["gemini-2.5-flash-lite", "gemini-2.0-flash"]

    settings = FakeSettingsStore()
    settings.set("gemini_model", "removed-model")
    services = SimpleNamespace(generator=Generator(), settings=settings)
    combo = QComboBox()
    qtbot.addWidget(combo)
    notifications = []
    changes = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notifications.append(args))
    combo.currentIndexChanged.connect(changes.append)
    populate_models(combo, services)
    qtbot.waitUntil(combo.isEnabled)
    assert combo.currentData() == settings.get("gemini_model")
    assert combo.currentData() != "removed-model"
    assert notifications and "removed-model" in notifications[0][2]
    assert not changes
