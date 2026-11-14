from main import create_window


def test_studio_window(qtbot, monkeypatch):
    from app.ui.services import ServiceContainer
    monkeypatch.setattr(ServiceContainer, "create_default", ServiceContainer.create_fake)
    window = create_window()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == 'TikTok YouTube Studio'
    assert window.isVisible()
    assert window.centralWidget() is not None
