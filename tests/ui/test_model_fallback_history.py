import json
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError

from app.contracts import VideoMeta, JobStatus
from app.errors import ContentInvalid, AuthExpired
from app.services.gemini.generator import GeminiContentGenerator
from app.services.fakes import FakeSettingsStore
from app.ui.services import ServiceContainer
from app.ui.main_window import MainWindow

META = VideoMeta('123', 'https://www.tiktok.com/@a/video/123', 'Title', 'Description', 'Author', None, 10, 720, 1280)


@pytest.fixture
def generator():
    client = Mock()
    models = ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3-flash',
              'gemini-image-flash', 'gemma-flash']
    client.models.list.return_value = [SimpleNamespace(name='models/' + name, supported_actions=['generateContent']) for name in models]
    settings = FakeSettingsStore()
    settings.set('gemini_model', models[0])
    service = GeminiContentGenerator(api_key='dummy-test-only', settings_store=settings, client_factory=lambda key: client)
    service.list_models()
    return service, settings, client


def success():
    return Mock(text=json.dumps({'title': 'Valid title', 'description': 'Description', 'hashtags': ['Python'], 'tags': ['demo']}))


def test_404_switches_and_persists_successful_model(generator):
    service, settings, client = generator
    client.models.generate_content.side_effect = [APIError(404, {'error': {'message': 'not found'}}), success()]
    assert service.generate(META, {'model': 'gemini-2.5-flash-lite'}).title == 'Valid title'
    assert [call.kwargs['model'] for call in client.models.generate_content.call_args_list] == ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite']
    assert settings.get('gemini_model') == 'gemini-3.1-flash-lite'
    assert 'đã chuyển sang model gemini-3.1-flash-lite' in service.last_model_notice


@pytest.mark.parametrize('code', [400, 401, 403])
def test_non_404_does_not_switch(generator, code):
    service, settings, client = generator
    client.models.generate_content.side_effect = APIError(code, {'error': {'message': 'failure'}})
    with pytest.raises((ContentInvalid, AuthExpired)):
        service.generate(META, {'model': 'gemini-2.5-flash-lite'})
    assert client.models.generate_content.call_count == 1
    assert settings.get('gemini_model') == 'gemini-2.5-flash-lite'


def test_all_404_stops_at_three_text_flash_models(generator):
    service, settings, client = generator
    client.models.generate_content.side_effect = APIError(404, {'error': {'message': 'not found'}})
    with pytest.raises(ContentInvalid) as caught:
        service.generate(META, {'model': 'gemini-2.5-flash-lite'})
    assert client.models.generate_content.call_count == 3
    assert 'Cài đặt' in str(caught.value)
    assert all('image' not in call.kwargs['model'] and 'gemma' not in call.kwargs['model'] for call in client.models.generate_content.call_args_list)
    assert settings.get('gemini_model') == 'gemini-2.5-flash-lite'


@pytest.mark.parametrize('code', [400, 401, 403])
def test_fallback_stops_if_next_model_has_non_404(generator, code):
    service, settings, client = generator
    client.models.generate_content.side_effect = [APIError(404, {'error': {'message': 'not found'}}),
                                                APIError(code, {'error': {'message': 'failure'}})]
    with pytest.raises((ContentInvalid, AuthExpired)):
        service.generate(META, {'model': 'gemini-2.5-flash-lite'})
    assert client.models.generate_content.call_count == 2
    assert settings.get('gemini_model') == 'gemini-2.5-flash-lite'


def test_worker_notifies_ui_and_updates_model_selection(generator, qtbot):
    from app.workers.service_workers import GenerateContentWorker
    service, settings, client = generator
    client.models.generate_content.side_effect = [APIError(404, {'error': {'message': 'not found'}}), success()]
    container = ServiceContainer.create_fake()
    window = MainWindow(container)
    qtbot.addWidget(window)
    worker = GenerateContentWorker(service, META, {'model': 'gemini-2.5-flash-lite'})
    worker.signals.model_selected.connect(container.gemini_selection.changed)
    worker.run()
    assert 'đã chuyển sang model gemini-3.1-flash-lite' in window.page_dashboard.lbl_model_notice.text()
    assert window.page_ai.combo_model.currentData() == 'gemini-3.1-flash-lite'
    assert window.page_settings.combo_gemini_model.currentData() == 'gemini-3.1-flash-lite'


@pytest.mark.parametrize('record,expected', [
    ({'video_id': 'dry-run-001', 'tiktok_video_id': '7707272778080062740'}, '7707272778080062740'),
    ({'video_id': 'dry-run-001', 'local_mp4_path': 'downloads/local-video.mp4'}, 'local-video.mp4'),
    ({'video_id': 'local-video', 'local_mp4_path': 'downloads/local-video.mp4'}, 'local-video.mp4'),
])
def test_history_uses_tiktok_id_or_filename(qtbot, record, expected):
    container = ServiceContainer.create_fake()
    container.history.add(record | {'status': JobStatus.UPLOADED, 'dry_run': True})
    window = MainWindow(container)
    qtbot.addWidget(window)
    page = window.page_history
    page.refresh_history()
    from app.ui.pages.history_page import VideoDetailsDialog
    from PySide6.QtWidgets import QLabel
    details = VideoDetailsDialog(page._current_records[0], page)
    assert expected in ' '.join(label.text() for label in details.findChildren(QLabel))
    assert page.table.item(0, 3).text() == 'Chạy thử'
    assert not page._current_records[0]['youtube_video_id']
    assert not page._current_records[0]['youtube_url']



def test_generator_default_model_can_be_overridden_for_one_request(generator):
    service,settings,client=generator
    settings.set('gemini_default_model','gemini-3.1-flash-lite')
    client.models.generate_content.return_value=success()
    service.generate(META,{})
    assert client.models.generate_content.call_args.kwargs['model']=='gemini-3.1-flash-lite'
    service.generate(META,{'model':'gemini-2.5-flash-lite'})
    assert client.models.generate_content.call_args.kwargs['model']=='gemini-2.5-flash-lite'
    assert settings.get('gemini_default_model')=='gemini-3.1-flash-lite'
