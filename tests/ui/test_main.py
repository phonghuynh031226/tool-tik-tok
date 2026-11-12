from main import create_window


def test_empty_studio_window(qtbot):
    window = create_window()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == 'TikTok YouTube Studio'
    assert window.isVisible()
    assert window.centralWidget() is None
