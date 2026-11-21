"""Explicitly armed, single-job automation driven by Dashboard user edits/paste."""
from datetime import datetime, timezone
import re
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from app.core.automation import AutomationStore, RetryConfirmationRequired
from app.services.tiktok.url import validate_url, extract_video_id
from app.workers.service_workers import GenerateContentWorker, UploadYouTubeWorker, DryRunResult
from app.contracts import JobStatus, UploadRequest
from app.ui.components import ToastManager, ConfirmDialog
from PySide6.QtWidgets import QDialog

class AutomationController(QObject):
    changed = Signal()

    def __init__(self, services, dashboard, store, parent=None):
        super().__init__(parent)
        self.services, self.page, self.store = services, dashboard, store
        self.armed_prompt_id = None  # Stored selection never grants execution after restart.
        self.channel_id = None
        from app.ui.batch_queue import BatchRunner
        self.batch = BatchRunner(self)
        self.job = None
        self.stage = ''
        self.stopping = False
        self.message = 'Tự động hóa đang tắt'
        self._text = ''
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self._start_pending)
        dashboard.input_url.textEdited.connect(self.consider_text)
        dashboard.paste_requested.connect(self.consider_text)
        dashboard.metadata_ready.connect(self._metadata_ready)
        dashboard.state.video_ready.connect(self._video_ready)
        dashboard.automation_completed.connect(self._completed)
        dashboard.workflow_error.connect(self._failed)
        dashboard.workflow_cancelled.connect(self._cancelled)

    @property
    def busy(self):
        return self.job is not None

    def _notify(self, kind, title, message):
        manager = ToastManager.instance()
        if manager:
            getattr(manager, kind)(title, message)

    def arm(self, prompt_id, channel_id, *, rights_confirmed=False, upload_confirmed=False):
        if self.batch.active:
            raise ValueError('Dừng hàng đợi trước khi đổi prompt hoặc kênh.')
        if self.busy or self.services.connection.busy:
            raise ValueError('Chờ tác vụ/kết nối hiện tại hoàn tất trước khi đổi prompt.')
        if rights_confirmed is not True or upload_confirmed is not True:
            raise ValueError('Phải xác nhận quyền sử dụng và cho phép tự đăng riêng biệt.')
        account = next((a for a in self.services.connection.accounts if a.id == channel_id and a.status == 'connected'), None)
        if account is None or (not self.services.is_fake and not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel_id)):
            raise ValueError('Chọn một kênh YouTube đang kết nối.')
        prompt = self.store.get_prompt(prompt_id)
        if prompt is None:
            raise ValueError('Prompt không còn tồn tại.')
        self.timer.stop()
        self._text = ""
        self.store.set_active(prompt_id)
        self.armed_prompt_id, self.channel_id = prompt_id, channel_id
        self.channel_title = account.title
        self.message = f"Hoạt động: {prompt['name']} • {account.title} — dán link ở Tổng quan"
        self.changed.emit()

    def deactivate(self):
        self.batch.abort_local()
        self.armed_prompt_id = None
        self.store.set_active(None)
        self.timer.stop()
        if self.busy:
            self.stopping = True
            self.message = 'Đang dừng tự động hóa…'
            self._cancel_workers()
        else:
            self.message = 'Tự động hóa đang tắt'
        self.changed.emit()

    @Slot(str)
    def consider_text(self, text):
        if self.page.batch_panel.multiple or self.batch.active or not self.armed_prompt_id or self.busy:
            return
        self._text = text.strip()
        self.timer.start()

    def _start_pending(self):
        if not self.armed_prompt_id or self.busy or self._text != self.page.input_url.text().strip():
            return
        try:
            url = validate_url(self._text)
            # Full video URLs and the two supported TikTok short-link hosts only.
            from urllib.parse import urlsplit
            if urlsplit(url).hostname not in {'vt.tiktok.com', 'vm.tiktok.com'}:
                extract_video_id(url)
        except Exception:
            return  # Incomplete user edits never start work.
        if any(getattr(self.page, name, None) is not None for name in (
            '_active_download_worker', '_active_ai_worker', '_active_upload_worker', '_active_fetch_worker')):
            self._notify('warning', 'Chưa chạy tự động', 'Chờ tác vụ thủ công hiện tại hoàn tất.')
            return
        if not self.services.connection.begin_upload(self.page):
            self._notify('warning', 'Chưa chạy tự động', 'Đang kết nối hoặc tải lên kênh YouTube.')
            return
        try:
            self.prompt = self.store.get_prompt(self.armed_prompt_id)
            self.policy = self.prompt['policy']
            try:
                self.job = self.store.claim(self.armed_prompt_id, url, self.channel_id)
            except RetryConfirmationRequired as previous:
                if self.batch.active:
                    raise ValueError('Video chưa rõ kết quả lần trước; kiểm tra lịch sử trước khi thử lại.')
                dialog = ConfirmDialog(
                    title='Thử lại video chưa rõ kết quả?',
                    message='Lần trước ứng dụng bị ngắt; trạng thái này không có nghĩa video đã đăng. '
                            'Hãy kiểm tra kênh YouTube và lịch sử. Chỉ tiếp tục nếu video chưa được đăng hoặc hẹn giờ.',
                    confirm_text='Chưa đăng, thử lại', cancel_text='Hủy', parent=self.page)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self.services.connection.end_upload(self.page)
                    return
                if not self.armed_prompt_id:
                    self.services.connection.end_upload(self.page)
                    return
                self.job = self.store.claim(self.armed_prompt_id, url, self.channel_id, retry_job_id=previous.job_id)
            self._ai_started = self._ai_done = self._download_done = False
            self.stage, self.stopping = 'downloading', False
            self.page._reset_form()
            self.page.input_url.setText(url)
            self.page.state.channel_id = self.channel_id
            self.message = f"{self.prompt['name']} • Đang tải video"
            self._controls(True)
            self.changed.emit()
            self.page._on_download_clicked()
        except Exception as error:
            self.services.connection.end_upload(self.page)
            if self.job:
                self._failed(str(error))
            else:
                self._notify('warning', 'Không chạy tự động', str(error))

    def _controls(self, busy):
        for widget in (self.page.input_url, self.page.btn_paste, self.page.btn_reset_job,
                       self.page.btn_download, self.page.btn_generate_ai, self.page.btn_restore_original,
                       self.page.edit_title, self.page.edit_desc, self.page.edit_hashtags, self.page.edit_tags):
            widget.setEnabled(not busy)
        if busy:
            self.page.btn_upload.setEnabled(False)
            self.page.btn_dry_run.setEnabled(False)
        else:
            self.page._update_upload_button_state()

    @Slot(str)
    def _video_ready(self, _path):
        if self.busy and self.stage in ('downloading', 'generating'):
            self._controls(True)
            QTimer.singleShot(0, self._after_download)

    def _after_download(self):
        if not self.busy or self.stage not in ('downloading', 'generating'):
            return
        if self.stopping:
            self._cancelled(); return
        try:
            meta = self.page.state.meta
            self.source_video_id = meta.video_id
            self.source_path = self.page.state.local_video_path
            self.store.bind_video(self.job['id'], meta.video_id)
            if self.services.history.find_by_video_id(meta.video_id):
                raise ValueError('Video nguồn đã có trong lịch sử; không tự đăng lại.')
            self._download_done = True
            if self._ai_started:
                self._after_generate()
                return
            self._begin_generate(meta)
        except Exception as error:
            self._failed(str(error))

    def _metadata_ready(self, meta):
        if (self.busy and not self.stopping and not self._ai_started
                and not self.services.settings.get('analyze_video_file', False)):
            try:
                self.source_video_id = meta.video_id
                self.store.bind_video(self.job['id'], meta.video_id)
                if self.services.history.find_by_video_id(meta.video_id):
                    raise ValueError('Video nguồn đã có trong lịch sử; không tự đăng lại.')
                self._begin_generate(meta)
            except Exception as error:
                self._failed(str(error))

    def _begin_generate(self, meta):
        try:
            self._ai_started = True
            self.stage = 'generating'
            self.store.mark_job(self.job['id'], self.stage)
            self.message = f"{self.prompt['name']} • " + ('Đang tạo nội dung AI' if self._download_done else 'Đang tải video và tạo nội dung AI')
            self.page.progress_ai.setValue(20)
            self.page.progress_ai.show()
            settings = {'model': self.page.combo_model.currentData() or self.services.settings.get('gemini_model'),
                        'video_path': str(self.page.state.local_video_path) if self._download_done else None,
                        'analyze_video_file': bool(self.services.settings.get('analyze_video_file', False)), 'timeout': 60}
            if self.policy.content_instructions:
                from app.services.gemini.generator import DEFAULT_PROMPT_TEMPLATE
                instructions = self.policy.content_instructions.replace('{', '{{').replace('}', '}}')
                settings['prompt_template'] = DEFAULT_PROMPT_TEMPLATE + '\nYêu cầu nội dung của người dùng: ' + instructions
            worker = GenerateContentWorker(self.services.generator, meta, settings)
            self.page._active_ai_worker = worker
            worker.signals.progress.connect(lambda value: self.page.progress_ai.setValue(int(value * 100)))
            job_id = self.job['id']
            worker.signals.finished.connect(lambda _content: self._clear_ai_worker(worker))
            worker.signals.error.connect(lambda _error: self._clear_ai_worker(worker))
            worker.signals.cancelled.connect(lambda: self._clear_ai_worker(worker))
            worker.signals.finished.connect(lambda content: self._generated(content) if self.job and self.job['id'] == job_id else None)
            worker.signals.error.connect(lambda message: self.page._on_worker_error(message) if self.job and self.job['id'] == job_id else None)
            worker.signals.cancelled.connect(lambda: self._cancelled() if self.job and self.job['id'] == job_id else None)
            self._controls(True)
            self.changed.emit()
            self.page.thread_pool.start(worker)
        except Exception as error:
            self._failed(str(error))

    @Slot(object)
    def _generated(self, content):
        # Only the worker created by this controller can advance the job.
        if not self.busy or self.stage != 'generating':
            return
        if self.stopping:
            self._cancelled(); return
        self._ai_done = True
        self.generated_content = content
        self.page._on_generate_finished(content)
        self._controls(True)
        QTimer.singleShot(0, self._after_generate)

    def _after_generate(self):
        if not self.busy or self.stage != 'generating':
            return
        if self.stopping:
            self._cancelled(); return
        if not self._download_done or not self._ai_done:
            return
        try:
            state = self.page.state
            if state.meta is None or state.meta.video_id != self.source_video_id or state.local_video_path != self.source_path or state.content is not self.generated_content:
                raise ValueError('Dữ liệu tác vụ đã thay đổi trong khi chạy. Không tự đăng video khác.')
            state.channel_id = self.channel_id
            state.privacy = self.policy.privacy
            state.made_for_kids = self.policy.made_for_kids
            state.rights_confirmed = True  # Only reached from explicit session activation.
            publish_at = self.job['publish_at']
            if publish_at is not None:
                if (publish_at - datetime.now(timezone.utc)).total_seconds() < 600:
                    raise ValueError('Giờ hẹn còn dưới 10 phút sau khi xử lý. Tác vụ dừng, không chuyển sang đăng ngay.')
                self.page.radio_publish_schedule.setChecked(True)
                self.page.schedule_picker.set_datetime(publish_at)
            state.publish_at = publish_at
            if self.services.is_fake:
                # Fake mode demonstrates stages only, never calls any upload method.
                self.page._on_upload_finished(DryRunResult(state.title, state.privacy, state.local_video_path, self.channel_title))
                self.store.finish(self.job['id'])
                self._release('Mô phỏng hoàn tất • Không đăng YouTube thật')
                self.page._reset_form()
                return
            req = state.build_upload_request()
            self.stage = 'uploading'
            self.store.mark_job(self.job['id'], self.stage)  # Persist BEFORE network side effect.
            self.message = f"{self.prompt['name']} • Đang tải lên {self.channel_title}"
            self.page.progress_upload.setValue(0)
            self.page.progress_upload.show()
            self.page.btn_cancel_upload.show()
            worker = UploadYouTubeWorker(self.services.youtube, req, confirmed_channel_id=self.channel_id,
                                        confirmed_channel_title=self.channel_title)
            self.page._active_upload_worker = worker
            worker.signals.progress.connect(lambda value: self.page.progress_upload.setValue(int(value * 100)))
            worker.signals.finished.connect(self.page._on_upload_finished)
            worker.signals.error.connect(self.page._on_worker_error)
            worker.signals.cancelled.connect(self.page._on_upload_cancelled)
            self._controls(True)
            self.changed.emit()
            self.page.thread_pool.start(worker)
        except Exception as error:
            self._failed(str(error))

    @Slot(object)
    def _completed(self, _result):
        if self.busy:
            self.store.finish(self.job['id'])
            try:
                for record in self.services.history.list(limit=1000):
                    if record.get('batch_failure') and record.get('url')==self._text and record.get('channel_id')==self.channel_id:
                        self.services.history.update(record['id'],dict(retry_resolved=True))
            except Exception:
                self._notify('warning','Lịch sử chưa đồng bộ','Video đã đăng; chưa cập nhật được bản ghi lỗi cũ.')
            self._release('Hoàn tất • Sẵn sàng nhận link tiếp theo' if self.armed_prompt_id else 'Tự động hóa đang tắt')

    @Slot(str)
    def _failed(self, message):
        if not self.busy:
            return
        self._cancel_workers()
        status = 'uncertain' if self.stage == 'uploading' else 'failed'
        self.store.mark_job(self.job['id'], status)
        self.batch.record_error(message)
        skip=self.batch.can_skip(message)
        retry=skip and self.batch.current and self.batch.current.get('can_retry') and self.batch.current.get('retries',0)<1
        if self.stage!='uploading' and not retry:
            try:
                self.batch.save_failure(message)
            except Exception:
                skip=False
                message='Không lưu được link lỗi vào lịch sử. '+message
        if not skip:
            self.armed_prompt_id = None
            self.store.set_active(None)
        self._release('Đã bỏ qua video lỗi • Tiếp tục hàng đợi' if skip else 'Đã dừng do lỗi • Kiểm tra tác vụ trước khi bật lại')
        self._notify('error', 'Video lỗi' if skip else 'Tự động hóa đã dừng', message or 'Không hoàn tất tác vụ.')

    @Slot()
    def _cancelled(self):
        if not self.busy:
            return
        self._cancel_workers()
        self.store.mark_job(self.job['id'], 'uncertain' if self.stage == 'uploading' else 'cancelled')
        self.armed_prompt_id = None
        self.store.set_active(None)
        self.page._active_ai_worker = None
        self.page._active_download_worker = None
        self.page._active_fetch_worker = None
        self.page.progress_ai.hide()
        self.page.progress_download.hide()
        self._release('Đã dừng tự động hóa')

    def _clear_ai_worker(self, worker):
        if self.page._active_ai_worker is worker:
            self.page._active_ai_worker = None

    def _cancel_workers(self):
        for name in ('_active_ai_worker', '_active_download_worker', '_active_fetch_worker', '_active_upload_worker'):
            worker = getattr(self.page, name, None)
            if worker is not None:
                worker.cancel()

    def _release(self, message):
        self.services.connection.end_upload(self.page)
        self.job, self.stage, self.stopping = None, '', False
        self.message = message
        self._controls(False)
        self.changed.emit()
