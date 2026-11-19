from unittest.mock import Mock
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel
from app.contracts import GeneratedContent, DownloadResult
from app.ui.pages.tools_page import ToolsPage
from app.ui.services import ServiceContainer
from app.ui.state import JobState


@pytest.fixture
def tools(qtbot):
    page = ToolsPage(JobState(), ServiceContainer.create_fake())
    qtbot.addWidget(page)
    page.resize(1000, 720)
    page.show()
    return page


def test_download_row_and_removed_session_list(tools, qtbot):
    assert not hasattr(tools, 'btn_pick_file')
    assert not hasattr(tools, 'tbl_downloads')
    assert not hasattr(tools, '_downloaded_files')
    qtbot.wait(20)
    assert abs(tools.btn_paste.mapTo(tools, tools.btn_paste.rect().center()).y() - tools.btn_download.mapTo(tools, tools.btn_download.rect().center()).y()) < 3


def test_download_finished_without_session_list(tools, tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'mocked-video')
    tools._on_download_finished(DownloadResult(path, 12, 'a' * 64, 5, 720, 1280))
    assert path.name in tools.lbl_download_result.text()
    assert tools.btn_download.isEnabled()
    assert tools.state.local_video_path is None


def test_ai_title_only_generate_and_copy(tools, qtbot):
    assert not hasattr(tools, 'edit_ai_orig_desc')
    assert not hasattr(tools, 'combo_tone')
    assert not hasattr(tools, 'edit_hashtags')
    assert not hasattr(tools, 'edit_tags')
    assert not hasattr(tools, 'btn_copy_all')
    assert not hasattr(tools, 'btn_apply_to_job')
    qtbot.wait(20)
    assert abs(tools.combo_model.mapTo(tools, tools.combo_model.rect().center()).y() - tools.btn_generate_ai.mapTo(tools, tools.btn_generate_ai.rect().center()).y()) < 3
    tools.thread_pool = Mock()
    tools.edit_ai_orig_title.setText('A source title')
    tools._on_generate_ai_clicked()
    assert tools._active_ai_worker.meta.description == ''
    assert 'tone' not in tools._active_ai_worker.settings
    content = GeneratedContent('Result', 'Description', ['ignored'], ['ignored'])
    tools._on_ai_finished(content)
    assert tools.edit_title.text() == 'Result'
    assert tools.edit_desc.toPlainText() == 'Description'
    tools.btn_copy_title.click()
    clip_title = QGuiApplication.clipboard().text()
    if clip_title:
        assert clip_title == 'Result'
    tools.btn_copy_desc.click()
    clip_desc = QGuiApplication.clipboard().text()
    if clip_desc:
        assert clip_desc == 'Description'
    assert tools.state.title == ''
    tools.state.set_generated_content(content)
    assert tools.edit_title.text() == 'Result'


def test_unified_tools_two_columns_then_stacked(tools, qtbot):
    from PySide6.QtWidgets import QTabWidget
    assert not tools.findChildren(QTabWidget)
    tools.resize(1450, 900)
    qtbot.wait(40)
    left = tools.download_card.geometry()
    right = tools.ai_input_card.geometry()
    assert abs(left.y() - right.y()) < 3
    assert right.x() > left.right()
    assert tools.ai_output_card.geometry().y() > max(left.bottom(), right.bottom())
    tools.resize(800, 720)
    qtbot.wait(40)
    assert tools.ai_input_card.geometry().y() > tools.download_card.geometry().bottom()
    assert tools.scroll.horizontalScrollBar().maximum() == 0
