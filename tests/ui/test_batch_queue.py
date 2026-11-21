from app.ui.batch_queue import parse_links


def test_parse_links_deduplicates_tiktok_identity_and_rejects_invalid():
    rows = parse_links('https://www.tiktok.com/@a/video/123\nhttps://www.tiktok.com/@a/video/123?x=1\nhttps://example.org/x\n')
    assert [r['status'] for r in rows] == ['waiting', 'duplicate', 'invalid']


def test_multilink_paste_adds_newline(qtbot):
    from app.ui.batch_queue import LinkEditor
    from PySide6.QtCore import QMimeData
    editor = LinkEditor()
    qtbot.addWidget(editor)
    mime = QMimeData(); mime.setText('https://www.tiktok.com/@a/video/123')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText().endswith('\n')


from tests.ui.test_automation_ui import configured, CHANNEL, URL
from app.core.automation import AutomationPolicy
from dataclasses import replace


def setup_batch(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    meta=services.tiktok.fetch_metadata.return_value
    from app.services.tiktok.url import extract_video_id
    services.tiktok.fetch_metadata.side_effect=lambda url: replace(meta,video_id=extract_video_id(url),url=url)
    pid=services.automation_store.add_prompt('Batch','Automatic batch',AutomationPolicy())
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    panel=window.page_dashboard.batch_panel
    panel.mode.setCurrentIndex(1)
    panel.editor.setPlainText(URL+'\n'+URL.replace('1234567890','2234567890')+'\n')
    return window,services,panel


def test_batch_waits_for_start_and_uploads_in_order(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    qtbot.wait(800)
    services.tiktok.fetch_metadata.assert_not_called()
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=12000)
    assert services.youtube.upload.call_count==2
    assert [call.args[0] for call in services.tiktok.fetch_metadata.call_args_list]==[r['url'] for r in panel.rows]
    assert [r['status'] for r in panel.rows]==['done','done']
    panel.start.click(); qtbot.wait(200)
    assert services.youtube.upload.call_count==2


def test_pause_finishes_current_then_resume(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    batch=window.automation.batch
    panel.start.click(); batch.pump(); panel.pause.click()
    qtbot.waitUntil(lambda:not window.automation.busy,timeout=8000)
    qtbot.wait(200)
    assert services.youtube.upload.call_count==1
    assert panel.rows[1]['status']=='waiting'
    panel.pause.click()
    qtbot.waitUntil(lambda:not batch.active,timeout=8000)
    assert services.youtube.upload.call_count==2


def test_global_error_stops_without_upload(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    services.generator.generate.side_effect=RuntimeError('quota unavailable')
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=8000)
    services.youtube.upload.assert_not_called()
    assert panel.rows[0]['status']=='error'
    assert panel.rows[1]['status']=='waiting'



def test_source_error_skips_to_next_and_keeps_queue_armed(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    from app.errors import DownloadFailed
    error=DownloadFailed(); error.user_message='Video không tồn tại'
    get_meta=services.tiktok.fetch_metadata.side_effect
    services.tiktok.fetch_metadata.side_effect=lambda url: (_ for _ in ()).throw(error) if url==URL else get_meta(url)
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=12000)
    assert [r['status'] for r in panel.rows]==['error','done']
    services.youtube.upload.assert_called_once()


def test_stop_before_start_and_prompt_cannot_change_during_batch(qtbot,tmp_path):
    import pytest
    window,services,panel=setup_batch(qtbot,tmp_path)
    panel.start.click()
    with pytest.raises(ValueError):
        window.automation.arm(window.automation.armed_prompt_id,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    panel.stop.click(); qtbot.wait(200)
    services.tiktok.fetch_metadata.assert_not_called()
    assert not window.automation.batch.active


def test_stop_active_download_cancels_and_never_advances(qtbot,tmp_path):
    from threading import Event
    window,services,panel=setup_batch(qtbot,tmp_path)
    entered=Event()
    original=services.tiktok.download.side_effect
    def download(meta,dest_dir,on_progress,cancel_token):
        entered.set()
        while not cancel_token.is_cancelled:
            import time
            time.sleep(.01)
        cancel_token.raise_if_cancelled()
    services.tiktok.download.side_effect=download
    panel.start.click()
    qtbot.waitUntil(entered.is_set,timeout=4000)
    panel.stop.click()
    qtbot.waitUntil(lambda:not window.automation.busy,timeout=4000)
    qtbot.wait(150)
    services.youtube.upload.assert_not_called()
    assert panel.rows[0]['status']=='cancelled'
    assert panel.rows[1]['status']=='waiting'



def test_ai_timeout_keeps_error_reason_and_continues(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    original=services.generator.generate.return_value
    from app.errors import NetworkError
    error=NetworkError(); error.user_message='Quá thời gian tạo nội dung AI. Vui lòng thử lại.'
    services.generator.generate.side_effect=[error,original,original]
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=12000)
    assert [r['status'] for r in panel.rows]==['done','done']
    assert panel.rows[0]['retries']==1
    assert not panel.rows[0]['error']
    assert services.youtube.upload.call_count==2


def test_preview_and_upload_include_hashtags_once(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    state=window.page_dashboard.state
    from app.contracts import GeneratedContent
    state.set_generated_content(GeneratedContent('Title','Description #Python',['Python','coding'],[]))
    assert '#coding' in window.page_dashboard.edit_desc.toPlainText()
    description=state.upload_description()
    assert description.count('#Python')==1
    assert description.count('#coding')==1




def test_one_retry_then_failed_link_saved(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    from app.errors import NetworkError
    error=NetworkError(); error.user_message='Quá thời gian tạo nội dung AI. Vui lòng thử lại.'
    content=services.generator.generate.return_value
    services.generator.generate.side_effect=[error,error,content]
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=15000)
    assert [r['status'] for r in panel.rows]==['error','done']
    assert panel.rows[0]['retries']==1
    failed=[r for r in services.history.list() if r.get('batch_failure')]
    assert len(failed)==1 and failed[0]['url']==URL
    assert 'thời gian' in failed[0]['error_message']
    services.youtube.upload.assert_called_once()


def test_failed_history_red_and_retry_action(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    from app.ui.pages.history_page import HistoryPage
    from app.ui.components import AppButton
    services.history.add(dict(video_id='failed-link',url=URL,title='Failed',status='FAILED',batch_failure=True,error_message='AI timeout'))
    page=HistoryPage(window.page_dashboard.state,services)
    qtbot.addWidget(page)
    assert page._presentation(page._all_records[0])[1]=='danger'
    assert any(b.text()=='Chạy lại' for b in page.findChildren(AppButton))



def test_retry_history_button_runs_only_failed_link(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    from app.ui.pages.history_page import HistoryPage
    from app.ui.components import AppButton
    services.history.add(dict(video_id='batch-error-old',url=URL,title='Failed',status='FAILED',channel_id=CHANNEL,batch_failure=True,error_message='AI timeout'))
    page=HistoryPage(window.page_dashboard.state,services,window)
    qtbot.addWidget(page)
    button=next(b for b in page.findChildren(AppButton) if b.text()=='Chạy lại')
    button.click()
    qtbot.waitUntil(lambda:services.youtube.upload.call_count==1,timeout=8000)
    qtbot.waitUntil(lambda:not window.automation.busy,timeout=8000)
    assert services.tiktok.fetch_metadata.call_args.args[0]==URL
    page.refresh_history()
    assert not any(r.get('batch_failure') for r in page._all_records)



def test_failed_link_survives_sqlite_reopen(qtbot,tmp_path):
    window,services,panel=setup_batch(qtbot,tmp_path)
    from app.db.repository import SQLiteHistoryRepository
    from app.errors import NetworkError
    repository=SQLiteHistoryRepository(tmp_path/'history.db')
    services.history=repository
    error=NetworkError(); error.user_message='Quá thời gian tạo nội dung AI. Vui lòng thử lại.'
    content=services.generator.generate.return_value
    services.generator.generate.side_effect=[error,error,content]
    panel.start.click()
    qtbot.waitUntil(lambda:not window.automation.batch.active,timeout=15000)
    repository.close()
    reopened=SQLiteHistoryRepository(tmp_path/'history.db')
    try:
        failed=[r for r in reopened.list() if r.get('batch_failure')]
        assert len(failed)==1
        assert failed[0]['url']==URL and failed[0]['retry_count']==1
        assert 'thời gian' in failed[0]['error_message']
    finally:
        reopened.close()
