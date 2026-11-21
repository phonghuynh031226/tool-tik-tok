from unittest.mock import Mock
from PySide6.QtGui import QGuiApplication
from app.contracts import ChannelAccount, ChannelInfo, VideoMeta, DownloadResult, GeneratedContent, UploadResult
from app.core.automation import AutomationStore, AutomationPolicy
from app.services.youtube.service import YouTubeService
from app.ui.services import ServiceContainer
from app.ui.main_window import MainWindow

CHANNEL='UC'+'a'*22
URL='https://www.tiktok.com/@demo/video/1234567890'


def configured(qtbot,tmp_path):
    services=ServiceContainer.create_fake()
    services.automation_store=AutomationStore(':memory:')
    services.youtube=Mock(spec=YouTubeService)
    services.youtube.list_accounts.return_value=[ChannelAccount(CHANNEL,'Test channel',is_default=True)]
    services.youtube.get_channel.return_value=ChannelInfo(CHANNEL,'Test channel')
    services.youtube.upload.return_value=UploadResult('v'*11,'https://www.youtube.com/watch?v='+'v'*11,CHANNEL)
    services.settings.set('download_dir',str(tmp_path))
    meta=VideoMeta('1234567890',URL,'Source','Description','Demo',None,5,720,1280)
    services.tiktok.fetch_metadata=Mock(return_value=meta)
    def download(meta,dest_dir,on_progress,cancel_token):
        path=dest_dir/'demo.mp4'; path.write_bytes(b'mock-video')
        on_progress(1.0)
        return DownloadResult(path,10,'a'*64,5,720,1280)
    services.tiktok.download=Mock(side_effect=download)
    services.generator.generate=Mock(return_value=GeneratedContent('AI title','AI desc',['demo'],['tag']))
    services.connection.set_accounts(services.youtube.list_accounts.return_value)
    # Controller integration deliberately isolates Dashboard from unrelated settings UI.
    from PySide6.QtWidgets import QMainWindow
    from app.ui.pages.dashboard import DashboardPage
    from app.ui.pages.automation_page import AutomationPage
    from app.ui.automation_controller import AutomationController
    from app.ui.components import ToastManager
    from app.ui.state import JobState
    window=QMainWindow()
    window.job_state=JobState(window)
    window.page_dashboard=DashboardPage(window.job_state,services,window)
    window.setCentralWidget(window.page_dashboard)
    window.toast_manager=ToastManager(window)
    window.automation=AutomationController(services,window.page_dashboard,services.automation_store,window)
    window.page_automation=AutomationPage(services,window.automation,window)
    qtbot.addWidget(window)
    return window, services


def test_dashboard_paste_automatic_mock_pipeline(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    pid=services.automation_store.add_prompt('Public','Tự tải, tạo nội dung và đăng công khai, không dành cho trẻ em',AutomationPolicy(privacy='public'))
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    window.page_dashboard.input_url.setText(URL)
    assert not window.automation.timer.isActive()
    services.youtube.upload.assert_not_called()
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard._on_paste_clicked()
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=8000)
    services.youtube.upload.assert_called_once()
    req=services.youtube.upload.call_args.args[0]
    assert req.privacy=='public' and req.made_for_kids is False
    assert req.rights_confirmed and req.channel_id==CHANNEL
    assert req.title=='AI title'
    services.youtube.confirm_upload.assert_called_once()
    assert services.automation_store.list_jobs()[0]['status']=='done'
    assert services.history.list()[0]['youtube_video_id']=='v'*11
    assert not window.page_dashboard.input_url.text()


def test_one_active_prompt_and_off_do_not_run(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    store=services.automation_store
    one=store.add_prompt('One','First',AutomationPolicy())
    two=store.add_prompt('Two','Second',AutomationPolicy())
    window.automation.arm(one,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    window.automation.arm(two,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    assert window.automation.armed_prompt_id==two
    assert sum(bool(p['active']) for p in store.list_prompts())==1
    window.automation.deactivate()
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard._on_paste_clicked()
    assert not window.automation.timer.isActive()
    services.tiktok.fetch_metadata.assert_not_called()
    assert window.page_automation is not None


def test_activation_requires_separate_consent(qtbot,tmp_path):
    import pytest
    window,services=configured(qtbot,tmp_path)
    pid=services.automation_store.add_prompt('One','First',AutomationPolicy())
    with pytest.raises(ValueError):
        window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=False)


def start(window, services, policy=None, url=URL):
    pid=services.automation_store.add_prompt('Run','Tự tải, tạo AI và đăng, không dành cho trẻ em',policy or AutomationPolicy(privacy='public'))
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    QGuiApplication.clipboard().setText(url)
    window.page_dashboard._on_paste_clicked()
    return pid


def test_scheduled_prompt_preserves_future_private_upload(qtbot,tmp_path):
    from app.contracts import JobStatus
    from datetime import datetime, timezone, timedelta
    window,services=configured(qtbot,tmp_path)
    services.youtube.upload.return_value=UploadResult('v'*11,'https://www.youtube.com/watch?v='+'v'*11,CHANNEL,status=JobStatus.SCHEDULED)
    start(window,services,AutomationPolicy(interval_minutes=1))
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=8000)
    req=services.youtube.upload.call_args.args[0]
    assert req.privacy=='private'
    assert req.publish_at >= datetime.now(timezone.utc)+timedelta(minutes=10)


def test_off_during_ai_prevents_upload(qtbot,tmp_path):
    import threading
    window,services=configured(qtbot,tmp_path)
    started,release=threading.Event(),threading.Event()
    def generate(*args):
        started.set(); release.wait(5)
        return GeneratedContent('Generated','Desc',[],[])
    services.generator.generate.side_effect=generate
    try:
        start(window,services)
        qtbot.waitUntil(started.is_set,timeout=4000)
        window.automation.deactivate()
        assert window.automation.busy
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=4000)
    services.youtube.upload.assert_not_called()
    assert window.automation.armed_prompt_id is None
    assert services.automation_store.list_jobs()[0]['status']=='cancelled'


def test_generation_failure_allows_new_source_after_rearm(qtbot,tmp_path):
    from app.errors import ContentInvalid
    window,services=configured(qtbot,tmp_path)
    services.generator.generate.side_effect=ContentInvalid('Test failed generation')
    start(window,services)
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=5000)
    assert window.page_dashboard._active_ai_worker is None
    services.generator.generate.side_effect=None
    services.tiktok.fetch_metadata.return_value=VideoMeta('987654321',URL,'Second source','Desc','Demo',None,5,720,1280)
    start(window,services,url='https://www.tiktok.com/@demo/video/987654321')
    qtbot.waitUntil(lambda: len(services.automation_store.list_jobs())==2,timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=5000)
    services.youtube.upload.assert_called_once()


def test_rearm_cancels_pending_paste(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    one=services.automation_store.add_prompt('One','First',AutomationPolicy())
    two=services.automation_store.add_prompt('Two','Second',AutomationPolicy())
    window.automation.arm(one,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    window.page_dashboard.input_url.setText(URL)
    window.automation.consider_text(URL)
    window.automation.arm(two,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    assert not window.automation.timer.isActive()
    services.tiktok.fetch_metadata.assert_not_called()


def test_manual_timeout_retains_worker_until_cancelled(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    worker=Mock()
    window.page_dashboard._active_ai_worker=worker
    window.page_dashboard._on_generate_ui_timeout()
    worker.cancel.assert_called_once()
    assert window.page_dashboard._active_ai_worker is worker


def test_saved_prompt_is_not_armed_on_new_controller(qtbot,tmp_path):
    from app.ui.automation_controller import AutomationController
    window,services=configured(qtbot,tmp_path)
    pid=services.automation_store.add_prompt('Saved','Prompt',AutomationPolicy())
    services.automation_store.set_active(pid)
    controller=AutomationController(services,window.page_dashboard,services.automation_store,window)
    assert controller.armed_prompt_id is None


def test_add_prompt_analysis_and_save(qtbot,tmp_path):
    from app.ui.pages.automation_page import AddPromptDialog
    window,services=configured(qtbot,tmp_path)
    interpreter=Mock()
    interpreter.interpret.return_value=AutomationPolicy(privacy='public')
    dialog=AddPromptDialog(services,services.automation_store,window,interpreter=interpreter)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText('My prompt')
    dialog.prompt_edit.setPlainText('Tự tải, tạo nội dung, đăng công khai, không dành cho trẻ em')
    dialog.analyze_button.click()
    qtbot.waitUntil(dialog.save_button.isEnabled,timeout=3000)
    dialog.save_button.click()
    prompts=services.automation_store.list_prompts()
    assert len(prompts)==1 and prompts[0]['policy'].privacy=='public'


def test_failed_upload_reservation_is_uncertain(qtbot,tmp_path):
    from app.errors import NetworkError
    window,services=configured(qtbot,tmp_path)
    services.youtube.upload.side_effect=NetworkError('Mock connection lost')
    start(window,services)
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=6000)
    assert services.automation_store.list_jobs()[0]['status']=='uncertain'
    assert window.automation.armed_prompt_id is None
    assert window.page_dashboard._active_upload_worker is None


def test_unrelated_ai_result_cannot_advance_current_job(qtbot,tmp_path):
    import threading
    window,services=configured(qtbot,tmp_path)
    started,release=threading.Event(),threading.Event()
    def generate(*args):
        started.set(); release.wait(5)
        return GeneratedContent('Own result','Own description',[],[])
    services.generator.generate.side_effect=generate
    try:
        start(window,services)
        qtbot.waitUntil(started.is_set,timeout=4000)
        window.job_state.set_generated_content(GeneratedContent('Stale manual result','Wrong',[],[]))
        qtbot.wait(150)
        services.youtube.upload.assert_not_called()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=5000)
    assert services.youtube.upload.call_args.args[0].title=='Own result'


def test_fake_mode_never_calls_upload(qtbot,tmp_path):
    from app.ui.automation_controller import AutomationController
    window,services=configured(qtbot,tmp_path)
    from app.services.fakes import FakeYouTubeService
    services.youtube=FakeYouTubeService()
    services.youtube.upload=Mock(side_effect=AssertionError('No fake upload call'))
    account=next(a for a in services.youtube.list_accounts() if a.status=='connected')
    services.connection.set_accounts(services.youtube.list_accounts())
    pid=services.automation_store.add_prompt('Demo','Demo',AutomationPolicy())
    window.automation.arm(pid,account.id,rights_confirmed=True,upload_confirmed=True)
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard._on_paste_clicked()
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=5000)
    services.youtube.upload.assert_not_called()
    assert not services.history.list()


def test_cancelled_metadata_completion_does_not_start_download(qtbot,tmp_path):
    from app.core.cancel import CancelToken
    window,services=configured(qtbot,tmp_path)
    worker=Mock()
    worker.cancel_token=CancelToken()
    worker.cancel_token.cancel()
    window.page_dashboard._active_fetch_worker=worker
    window.page_dashboard._on_fetch_meta_finished(services.tiktok.fetch_metadata.return_value)
    services.tiktok.download.assert_not_called()
    assert window.page_dashboard._active_fetch_worker is None


def test_real_window_close_revokes_pending_permission(qtbot):
    services=ServiceContainer.create_fake()
    services.automation_store=AutomationStore(':memory:')  # Caller owns post-close inspection.
    services.connection.set_accounts(services.youtube.list_accounts())
    window=MainWindow(services)
    qtbot.addWidget(window)
    store=window.automation.store
    pid=store.add_prompt('Saved','Demo',AutomationPolicy())
    account=next(a for a in services.connection.accounts if a.status=='connected')
    window.automation.arm(pid,account.id,rights_confirmed=True,upload_confirmed=True)
    window.page_dashboard.input_url.setText(URL)
    window.automation.consider_text(URL)
    window.close()
    assert window.automation.armed_prompt_id is None
    assert not window.automation.timer.isActive()
    assert not store.list_jobs()


def test_control_v_triggers_user_paste(qtbot,tmp_path):
    from PySide6.QtCore import Qt
    window,services=configured(qtbot,tmp_path)
    window.show()
    pid=services.automation_store.add_prompt('Run','Demo',AutomationPolicy())
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard.input_url.setFocus()
    qtbot.keyClick(window.page_dashboard.input_url,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: bool(services.automation_store.list_jobs()),timeout=3000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=6000)
    services.youtube.upload.assert_called_once()


def test_off_during_blocked_ai_unlocks_before_api_returns(qtbot,tmp_path):
    import threading
    window,services=configured(qtbot,tmp_path)
    started,release=threading.Event(),threading.Event()
    def generate(*args):
        started.set()
        release.wait(8)
        return GeneratedContent('Late result','Late description',[],[])
    services.generator.generate.side_effect=generate
    try:
        start(window,services)
        qtbot.waitUntil(started.is_set,timeout=4000)
        window.automation.deactivate()
        qtbot.waitUntil(lambda: not window.automation.busy,timeout=1200)
        assert not release.is_set()
        assert window.page_dashboard.input_url.isEnabled()
        assert window.page_dashboard._active_ai_worker is None
        assert services.automation_store.list_jobs()[0]['status']=='cancelled'
        release.set()
        from app.workers.base import background_requests
        qtbot.waitUntil(lambda: not background_requests(), timeout=200)
        assert window.page_dashboard.state.title != 'Late result'
        services.youtube.upload.assert_not_called()
    finally:
        release.set()


def test_ai_worker_timeout_does_not_wait_for_api(qtbot):
    import threading
    from PySide6.QtCore import QThreadPool
    from app.workers.service_workers import GenerateContentWorker
    release=threading.Event()
    generator=Mock()
    generator.generate.side_effect=lambda *args: (release.wait(8), GeneratedContent('Late','Desc',[],[]))[1]
    worker=GenerateContentWorker(generator,None,timeout=0.1)
    errors,finished=[],[]
    worker.signals.error.connect(errors.append)
    worker.signals.finished.connect(finished.append)
    try:
        QThreadPool.globalInstance().start(worker)
        qtbot.waitUntil(lambda: bool(errors),timeout=1200)
        assert not release.is_set()
        assert not finished
        release.set()
        from app.workers.base import background_requests
        qtbot.waitUntil(lambda: not background_requests(), timeout=200)
        assert not finished
    finally:
        release.set()



def test_uncertain_source_retry_asks_once_then_runs(qtbot,tmp_path,monkeypatch):
    import app.ui.automation_controller as module
    from PySide6.QtWidgets import QDialog
    window,services=configured(qtbot,tmp_path)
    store=services.automation_store
    pid=store.add_prompt('Retry','Retry',AutomationPolicy())
    old=store.claim(pid,URL,CHANNEL)
    store.mark_job(old['id'],'uncertain')
    dialog=Mock()
    dialog.exec.return_value=QDialog.DialogCode.Accepted
    factory=Mock(return_value=dialog)
    monkeypatch.setattr(module,'ConfirmDialog',factory)
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard._on_paste_clicked()
    qtbot.waitUntil(lambda: services.youtube.upload.called,timeout=6000)
    qtbot.waitUntil(lambda: not window.automation.busy,timeout=3000)
    factory.assert_called_once()
    assert store.list_jobs()[0]['status']=='done'
    services.youtube.upload.assert_called_once()


def test_uncertain_source_retry_decline_never_downloads(qtbot,tmp_path,monkeypatch):
    import app.ui.automation_controller as module
    from PySide6.QtWidgets import QDialog
    window,services=configured(qtbot,tmp_path)
    store=services.automation_store
    pid=store.add_prompt('Retry','Retry',AutomationPolicy())
    old=store.claim(pid,URL,CHANNEL)
    store.mark_job(old['id'],'uncertain')
    dialog=Mock()
    dialog.exec.return_value=QDialog.DialogCode.Rejected
    factory=Mock(return_value=dialog)
    monkeypatch.setattr(module,'ConfirmDialog',factory)
    window.automation.arm(pid,CHANNEL,rights_confirmed=True,upload_confirmed=True)
    QGuiApplication.clipboard().setText(URL)
    window.page_dashboard._on_paste_clicked()
    qtbot.waitUntil(lambda: factory.called,timeout=2500)
    assert not window.automation.busy
    assert not services.connection.busy
    services.tiktok.fetch_metadata.assert_not_called()
    services.youtube.upload.assert_not_called()
    assert store.list_jobs()[0]['status']=='uncertain'



def test_enable_prompt_uses_default_channel_without_modal(qtbot,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QDialog
    window,services=configured(qtbot,tmp_path)
    prompt=services.automation_store.add_prompt('Direct enable','User prompt',AutomationPolicy())
    services.connection.selected_channel_id=CHANNEL
    def no_dialog(*args):
        raise AssertionError('Activation must not show a dialog')
    monkeypatch.setattr(QDialog,'exec',no_dialog)
    window.page_automation._toggle(prompt)
    assert window.automation.armed_prompt_id==prompt
    assert window.automation.channel_id==CHANNEL
    assert not window.automation.busy
    services.tiktok.fetch_metadata.assert_not_called()
    services.youtube.upload.assert_not_called()
    window.page_automation._toggle(prompt)
    assert window.automation.armed_prompt_id is None


def test_direct_enable_requires_existing_selected_channel(qtbot,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QDialog
    window,services=configured(qtbot,tmp_path)
    prompt=services.automation_store.add_prompt('Direct enable','User prompt',AutomationPolicy())
    services.connection.accounts=[ChannelAccount(CHANNEL,'No default',is_default=False)]
    services.connection.selected_channel_id=CHANNEL
    services.connection.channel=None
    window.page_automation._notice=Mock()
    monkeypatch.setattr(QDialog,'exec',lambda *args: (_ for _ in ()).throw(AssertionError('No modal')))
    window.page_automation._toggle(prompt)
    assert window.automation.armed_prompt_id is None
    window.page_automation._notice.assert_called_once()
    services.youtube.upload.assert_not_called()



def test_automatic_prompt_uses_default_not_dashboard_selection(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    other='UC'+'b'*22
    services.connection.set_accounts([ChannelAccount(CHANNEL,'Default',is_default=True),ChannelAccount(other,'Selected')])
    services.connection.selected_channel_id=other
    prompt=services.automation_store.add_prompt('Auto','User prompt',AutomationPolicy())
    window.page_automation._toggle(prompt)
    assert window.automation.channel_id==CHANNEL
    window.automation.deactivate()


def test_explicit_prompt_channel_overrides_default_and_is_locked(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    other='UC'+'b'*22
    services.connection.set_accounts([ChannelAccount(CHANNEL,'Default',is_default=True),ChannelAccount(other,'Chosen')])
    prompt=services.automation_store.add_prompt('Chosen','User prompt',AutomationPolicy(),target_channel_id=other)
    window.page_automation.refresh()
    window.page_automation._toggle(prompt)
    assert window.automation.channel_id==other
    from app.ui.pages.automation_page import AutomationCardWidget
    current=[card for card in window.page_automation.card_container.findChildren(AutomationCardWidget) if card.prompt['id']==prompt and card.is_active]
    assert current and not current[-1].combo_channel.isEnabled()
    window.automation.deactivate()


def test_create_prompt_saves_channel_selector(qtbot,tmp_path):
    from app.ui.pages.automation_page import AddPromptDialog
    window,services=configured(qtbot,tmp_path)
    interpreter=Mock()
    interpreter.interpret.return_value=AutomationPolicy()
    dialog=AddPromptDialog(services,services.automation_store,window,interpreter=interpreter)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText('Specific channel')
    dialog.prompt_edit.setPlainText('Tải TikTok tạo AI rồi đăng, không dành cho trẻ em')
    dialog.combo_channel.setCurrentIndex(dialog.combo_channel.findData(CHANNEL))
    dialog.analyze_button.click()
    qtbot.waitUntil(dialog.save_button.isEnabled,timeout=3000)
    dialog.save_button.click()
    assert services.automation_store.list_prompts()[0]['target_channel_id']==CHANNEL


def test_disconnected_fixed_target_does_not_fall_back_to_default(qtbot,tmp_path):
    window,services=configured(qtbot,tmp_path)
    prompt=services.automation_store.add_prompt('Missing','User prompt',AutomationPolicy(),target_channel_id='UC'+'b'*22)
    window.page_automation._notice=Mock()
    window.page_automation._toggle(prompt)
    assert window.automation.armed_prompt_id is None
    window.page_automation._notice.assert_called_once()



def test_card_channel_edit_persists_and_auto_follows_new_default_on_enable(qtbot,tmp_path):
    from app.ui.pages.automation_page import AutomationCardWidget
    window,services=configured(qtbot,tmp_path)
    other='UC'+'b'*22
    services.connection.set_accounts([ChannelAccount(CHANNEL,'First',is_default=True),ChannelAccount(other,'Second')])
    prompt=services.automation_store.add_prompt('Pick channel','User prompt',AutomationPolicy())
    window.page_automation.refresh()
    card=[c for c in window.page_automation.card_container.findChildren(AutomationCardWidget) if c.prompt['id']==prompt][-1]
    card.combo_channel.setCurrentIndex(card.combo_channel.findData(other))
    assert services.automation_store.get_prompt(prompt)['target_channel_id']==other
    window.page_automation._set_prompt_channel(prompt,None)
    services.connection.set_accounts([ChannelAccount(CHANNEL,'First'),ChannelAccount(other,'Second',is_default=True)])
    window.page_automation._toggle(prompt)
    assert window.automation.channel_id==other
    # Changing default after enable does not reroute an authorized session.
    services.connection.set_accounts([ChannelAccount(CHANNEL,'First',is_default=True),ChannelAccount(other,'Second')])
    assert window.automation.channel_id==other
    window.automation.deactivate()


import pytest
from threading import Event

@pytest.mark.parametrize('first', ['ai', 'download'])
def test_parallel_download_and_ai_join_before_upload(qtbot, tmp_path, first):
    window, services = configured(qtbot, tmp_path)
    download_started, ai_started = Event(), Event()
    allow_download, allow_ai = Event(), Event()
    original_download = services.tiktok.download.side_effect
    content = services.generator.generate.return_value
    def download(*args, **kwargs):
        download_started.set()
        assert allow_download.wait(6)
        return original_download(*args, **kwargs)
    def generate(meta, settings, *args, **kwargs):
        ai_started.set()
        assert settings['video_path'] is None
        assert allow_ai.wait(6)
        return content
    services.tiktok.download.side_effect = download
    services.generator.generate.side_effect = generate
    pid = services.automation_store.add_prompt('Parallel', 'Automatic workflow', AutomationPolicy(privacy='public'))
    window.automation.arm(pid, CHANNEL, rights_confirmed=True, upload_confirmed=True)
    window.page_dashboard.input_url.setText(URL)
    window.automation.consider_text(URL)
    try:
        qtbot.waitUntil(lambda: download_started.is_set() and ai_started.is_set(), timeout=4000)
        services.youtube.upload.assert_not_called()
        (allow_ai if first == 'ai' else allow_download).set()
        qtbot.wait(150)
        services.youtube.upload.assert_not_called()
        allow_ai.set(); allow_download.set()
        qtbot.waitUntil(lambda: not window.automation.busy, timeout=6000)
        services.youtube.upload.assert_called_once()
        assert services.automation_store.list_jobs()[0]['status'] == 'done'
    finally:
        allow_ai.set(); allow_download.set()


def test_mp4_analysis_waits_for_download(qtbot, tmp_path):
    window, services = configured(qtbot, tmp_path)
    services.settings.set('analyze_video_file', True)
    started, release = Event(), Event()
    original = services.tiktok.download.side_effect
    def download(*args, **kwargs):
        started.set()
        assert release.wait(6)
        return original(*args, **kwargs)
    services.tiktok.download.side_effect = download
    pid = services.automation_store.add_prompt('MP4', 'Automatic workflow', AutomationPolicy())
    window.automation.arm(pid, CHANNEL, rights_confirmed=True, upload_confirmed=True)
    window.page_dashboard.input_url.setText(URL)
    window.automation.consider_text(URL)
    try:
        qtbot.waitUntil(started.is_set, timeout=4000)
        qtbot.wait(100)
        services.generator.generate.assert_not_called()
        release.set()
        qtbot.waitUntil(lambda: not window.automation.busy, timeout=6000)
        settings = services.generator.generate.call_args.args[1]
        assert settings['analyze_video_file'] is True
        assert settings['video_path'].endswith('demo.mp4')
        services.youtube.upload.assert_called_once()
    finally:
        release.set()
