"""Explicitly started session queue; reuses the existing single-video automation."""
from urllib.parse import urlsplit
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPlainTextEdit, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
from app.ui import i18n
from app.ui.components import AppButton
from app.services.tiktok.url import validate_url, extract_video_id


def identity(url):
    try: return extract_video_id(url)
    except Exception: return urlsplit(url)._replace(query='', fragment='').geturl().rstrip('/')


def parse_links(text):
    rows, seen = [], set()
    for line in text.splitlines():
        raw = line.strip()
        if not raw: continue
        try:
            url = validate_url(raw)
            if urlsplit(url).hostname not in {'vt.tiktok.com', 'vm.tiktok.com'}: extract_video_id(url)
            key = identity(url)
            status = 'duplicate' if key in seen else 'waiting'
            seen.add(key)
        except Exception: url, status = raw, 'invalid'
        rows.append(dict(url=url, status=status))
    return rows


class LinkEditor(QPlainTextEdit):
    def insertFromMimeData(self, mime):
        text = mime.text().strip()
        if text:
            cursor = self.textCursor()
            if self.toPlainText() and not cursor.atBlockStart(): cursor.insertText('\n')
            cursor.insertText(text + '\n')
            self.setTextCursor(cursor)


class BatchPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.mode = QComboBox(self)
        i18n.add_item(self.mode, 'Một link', 'single'); i18n.add_item(self.mode, 'Nhiều link', 'batch')
        layout.addWidget(self.mode)
        self.body = QWidget(self); body = QVBoxLayout(self.body); body.setContentsMargins(0,0,0,0)
        self.editor = LinkEditor(self.body)
        i18n.placeholder(self.editor, 'Dán link TikTok, mỗi link một dòng…')
        self.editor.setMaximumHeight(125); body.addWidget(self.editor)
        self.summary = QLabel(self.body); self.summary.setWordWrap(True); body.addWidget(self.summary)
        self.paste = i18n.ui(AppButton('Dán danh sách', parent=self.body))
        self.start = i18n.ui(AppButton('Bắt đầu', variant='primary', parent=self.body))
        self.pause = i18n.ui(AppButton('Tạm dừng sau video này', parent=self.body))
        self.stop = i18n.ui(AppButton('Dừng hàng đợi', parent=self.body))
        self.retry = i18n.ui(AppButton('Thử lại link lỗi', parent=self.body))
        for buttons in ((self.paste,self.start),(self.pause,self.stop,self.retry)):
            row=QHBoxLayout()
            for button in buttons: row.addWidget(button)
            body.addLayout(row)
        self.table=QTableWidget(0,3,self.body)
        i18n.headers(self.table,['Link','Trạng thái','Lý do'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(140); body.addWidget(self.table)
        layout.addWidget(self.body); self.body.hide()
        self.mode.currentIndexChanged.connect(lambda: self.body.setVisible(self.multiple))
        self.paste.clicked.connect(self.paste_clipboard)
        self.rows=[]; self.editor.textChanged.connect(self.preview); self.preview()

    @property
    def multiple(self): return self.mode.currentData()=='batch'

    def paste_clipboard(self):
        from PySide6.QtCore import QMimeData
        mime=QMimeData(); mime.setText(QGuiApplication.clipboard().text()); self.editor.insertFromMimeData(mime)

    def preview(self):
        self.rows=parse_links(self.editor.toPlainText()); self.render()

    def render(self):
        captions={'waiting':'Chờ','duplicate':'Trùng link','invalid':'Link không hợp lệ','running':'Đang xử lý',
            'done':'Đã xử lý','scheduled':'Đã hẹn giờ','error':'Lỗi','blocked':'Cần kiểm tra','cancelled':'Đã dừng'}
        self.table.setRowCount(len(self.rows))
        for index,row in enumerate(self.rows):
            self.table.setItem(index,0,QTableWidgetItem(row['url']))
            self.table.setItem(index,1,QTableWidgetItem(i18n.translate(captions[row['status']],i18n.language_for(self))))
            item=QTableWidgetItem(row.get('error',''))
            item.setToolTip(row.get('error',''))
            self.table.setItem(index,2,item)
        i18n.format_text(self.summary,'Đã xử lý {0}/{1} · Trùng {2} · Không hợp lệ {3}',
            sum(r['status'] in {'done','scheduled'} for r in self.rows),
            sum(r['status'] not in {'duplicate','invalid'} for r in self.rows),
            sum(r['status']=='duplicate' for r in self.rows),sum(r['status']=='invalid' for r in self.rows))


class BatchRunner(QObject):
    def __init__(self, controller):
        super().__init__(controller)
        self.controller=controller; self.panel=controller.page.batch_panel
        self.active=self.paused=False; self.current=None
        self.panel.start.clicked.connect(self.start); self.panel.pause.clicked.connect(self.toggle_pause)
        self.panel.stop.clicked.connect(self.stop); self.panel.retry.clicked.connect(self.retry)
        self.panel.mode.currentIndexChanged.connect(self.mode_changed)
        controller.changed.connect(self.changed)
        self.timer=QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.pump)

    def mode_changed(self):
        c=self.controller
        if c.busy:
            self.panel.mode.blockSignals(True); self.panel.mode.setCurrentIndex(0 if self.panel.multiple else 1); self.panel.mode.blockSignals(False)
            self.panel.body.setVisible(self.panel.multiple); return
        c.timer.stop()
        for widget in (c.page.input_url,c.page.btn_paste,c.page.btn_download): widget.setVisible(not self.panel.multiple)

    def start(self):
        c=self.controller
        if self.active or c.busy: return
        if any(getattr(c.page,name,None) is not None for name in ('_active_ai_worker','_active_download_worker','_active_fetch_worker','_active_upload_worker')):
            c._notify('warning','Chưa chạy tự động','Chờ tác vụ hiện tại hoàn tất.'); return
        if not c.armed_prompt_id:
            c._notify('warning','Chưa chạy tự động','Bật một prompt tự động hóa và chọn kênh trước khi bắt đầu.'); return
        if not any(r['status']=='waiting' for r in self.panel.rows): return
        self.prompt_id,self.channel_id=c.armed_prompt_id,c.channel_id
        self.active,self.paused,self.current=True,False,None; c.timer.stop()
        for widget in (self.panel.editor,self.panel.paste,self.panel.mode,self.panel.start,self.panel.retry): widget.setEnabled(False)
        self.timer.start()

    def retry(self):
        if self.active: return
        for row in self.panel.rows:
            if row['status']=='error': row['status']='waiting'
        self.panel.render()

    def toggle_pause(self):
        if not self.active: return
        self.paused=not self.paused
        i18n.set_text(self.panel.pause,'Tiếp tục' if self.paused else 'Tạm dừng sau video này')

    def abort_local(self):
        if self.current:
            self.current['status']='blocked' if self.controller.stage=='uploading' else 'cancelled'
            self.current=None
        self.finish()

    def stop(self):
        if self.current:
            self.current['status']='blocked' if self.controller.stage=='uploading' else 'cancelled'
            self.current=None
        self.finish(); self.controller.deactivate()

    def finish(self):
        self.active=False; self.timer.stop()
        for widget in (self.panel.editor,self.panel.paste,self.panel.mode,self.panel.start,self.panel.retry): widget.setEnabled(True)
        i18n.set_text(self.panel.pause,'Tạm dừng sau video này'); self.panel.render()

    def can_skip(self, message):
        text=message.casefold()
        blocked=any(x in text for x in ('quota','hạn mức','đăng nhập','hết hạn','oauth','api key','khóa api','credential','tài khoản youtube','giờ hẹn','lịch hẹn'))
        known=any(x in text for x in ('thời gian','timeout','không thể kết nối mạng','không tải được video','không lấy được video','video không tồn tại','video đã bị xóa','video riêng tư','không tìm thấy video','video is unavailable','nội dung chưa hợp lệ'))
        return self.active and self.controller.stage in {'downloading','generating'} and not blocked and known

    def record_error(self, message):
        if self.active and self.current is not None:
            self.current['error']=message or 'Không hoàn tất tác vụ.'
            self.current['can_retry']=self.can_skip(message) and any(x in message.casefold() for x in
                ('thời gian','timeout','mạng','kết nối','thử lại','tạm thời'))

    def save_failure(self, message):
        c=self.controller
        from app.security.redaction import redact_text
        state=c.page.state
        failure_id='batch-error-'+c.job['id']
        record=dict(video_id=failure_id, url=c._text,
            title=state.title or c._text, status='FAILED', batch_failure=True,
            channel_id=c.channel_id, error_message=redact_text(message),
            retry_count=(self.current or {}).get('retries',0), automation_job_id=c.job['id'])
        existing=c.services.history.find_by_video_id(failure_id)
        if existing: c.services.history.update(existing['id'],record)
        else: c.services.history.add(record)


    def changed(self):
        c=self.controller
        if not self.active or c.busy or self.current is None: return
        record=next((j for j in c.store.list_jobs(limit=1000) if j['id']==self.current.get('job_id')),None)
        status=record['status'] if record else 'failed'
        row=self.current
        if status=='failed' and row.get('can_retry') and row.get('retries',0)<1:
            row['retries']=row.get('retries',0)+1
            row['status']='waiting'
            row['error']='Đang chờ thử lại 1/1: '+row.get('error','')
        else:
            row['status']=('scheduled' if record.get('publish_at') else 'done') if status=='done' else ('blocked' if status=='uncertain' else 'error')
            if status=='done':
                row['error']=''
                # Keep failed attempts in storage but suppress resolved failures in the normal history view.
                for previous in c.services.history.list(limit=1000):
                    if previous.get('batch_failure') and previous.get('url')==row['url'] and previous.get('channel_id')==c.channel_id:
                        c.services.history.update(previous['id'],dict(retry_resolved=True))
        self.current=None; self.panel.render()
        if not c.armed_prompt_id: self.finish()

    def pump(self):
        try:
            self._pump()
        except Exception:
            if self.current:
                self.current['status']='blocked'
                self.current=None
            self.finish()
            self.controller._notify('error','Hàng đợi đã dừng','Không thể tiếp tục hàng đợi. Kiểm tra tác vụ trước khi thử lại.')

    def _pump(self):
        c=self.controller
        if not self.active or c.busy or self.paused: return
        if c.armed_prompt_id!=self.prompt_id or c.channel_id!=self.channel_id: self.finish(); return
        if any(getattr(c.page,name,None) is not None for name in ('_active_ai_worker','_active_download_worker','_active_fetch_worker','_active_upload_worker')): return
        row=next((r for r in self.panel.rows if r['status']=='waiting'),None)
        if row is None: self.finish(); return
        prior=next((j for j in c.store.list_jobs(limit=1000) if j['channel_id']==self.channel_id and identity(j['source_url'])==identity(row['url'])),None)
        if prior and prior['status'] not in {'failed','cancelled'}:
            row['status']='blocked'; self.panel.render(); return
        self.current=row; row['status']='running'
        c.page.input_url.setText(row['url']); c._text=row['url']; c._start_pending()
        if c.job: row['job_id']=c.job['id']
        else: row['status']='blocked'; self.current=None
        self.panel.render()
