"""YouTube Upload dedicated page."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.contracts import UploadRequest, UploadResult
from app.ui.components import Card, UploadConfirmDialog
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import UploadYouTubeWorker


class YouTubePage(QWidget):
    """Dedicated YouTube upload configuration and publishing page."""

    def __init__(
        self,
        job_state: JobState,
        services: ServiceContainer,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.state = job_state
        self.services = services
        self.thread_pool = QThreadPool.globalInstance()
        self._active_upload_worker: Optional[UploadYouTubeWorker] = None

        self._init_ui()
        self._connect_state()
        self._refresh_channel()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header
        header = QLabel("Đăng Video Lên Kênh YouTube", container)
        header.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        layout.addWidget(header)

        sub = QLabel(
            "Cấu hình xuất bản video an toàn. Mặc định luôn là chế độ Riêng tư (Private) để bạn kiểm duyệt trước.",
            container,
        )
        sub.setProperty("class", "hintLabel")
        layout.addWidget(sub)

        # Channel Card
        ch_card = Card(title="Kênh YouTube đích", parent=container)
        ch_layout = QHBoxLayout()
        ch_layout.setSpacing(12)

        icon_label = QLabel("🔴")
        icon_label.setStyleSheet("font-size: 24px;")
        ch_layout.addWidget(icon_label)

        info_box = QVBoxLayout()
        self.lbl_channel_name = QLabel("Kênh: Đang kết nối...")
        self.lbl_channel_name.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        info_box.addWidget(self.lbl_channel_name)

        self.lbl_channel_id = QLabel("ID kênh: -")
        self.lbl_channel_id.setProperty("class", "hintLabel")
        info_box.addWidget(self.lbl_channel_id)
        ch_layout.addLayout(info_box, stretch=1)

        self.btn_refresh = QPushButton("Làm mới kết nối", ch_card)
        self.btn_refresh.clicked.connect(self._refresh_channel)
        ch_layout.addWidget(self.btn_refresh)

        ch_card.add_layout(ch_layout)
        layout.addWidget(ch_card)

        # Upload Parameters Card
        params_card = Card(title="Thông số đăng tải bắt buộc", parent=container)
        p_layout = QGridLayout()
        p_layout.setSpacing(14)

        # Privacy
        lbl_p = QLabel("Chế độ quyền riêng tư:", params_card)
        lbl_p.setProperty("class", "fieldLabel")
        p_layout.addWidget(lbl_p, 0, 0)

        self.combo_privacy = QComboBox(params_card)
        self.combo_privacy.addItem("Riêng tư (Private) - Mặc định an toàn", "private")
        self.combo_privacy.addItem("Không công khai (Unlisted)", "unlisted")
        self.combo_privacy.addItem("Công khai (Public)", "public")
        self.combo_privacy.currentIndexChanged.connect(self._on_privacy_changed)
        p_layout.addWidget(self.combo_privacy, 1, 0)

        # Made for Kids: KHÔNG CHỌN SẴN, BẮT BUỘC CHỌN
        lbl_k = QLabel("Nội dung dành cho trẻ em? (Bắt buộc chọn):", params_card)
        lbl_k.setProperty("class", "fieldLabel")
        p_layout.addWidget(lbl_k, 0, 1)

        kids_row = QHBoxLayout()
        self.radio_kids_yes = QRadioButton("Có, dành cho trẻ em", params_card)
        self.radio_kids_no = QRadioButton("Không, không dành cho trẻ em", params_card)
        self.kids_group = QButtonGroup(params_card)
        self.kids_group.addButton(self.radio_kids_yes, 1)
        self.kids_group.addButton(self.radio_kids_no, 0)
        self.radio_kids_yes.toggled.connect(self._on_kids_changed)
        self.radio_kids_no.toggled.connect(self._on_kids_changed)

        kids_row.addWidget(self.radio_kids_yes)
        kids_row.addWidget(self.radio_kids_no)
        kids_row.addStretch()
        p_layout.addLayout(kids_row, 1, 1)

        params_card.add_layout(p_layout)

        # Rights confirmation checkbox (MANDATORY)
        self.chk_rights = QCheckBox(
            "Tôi xác nhận có toàn quyền sở hữu hoặc quyền sử dụng hợp pháp video này theo chính sách YouTube.",
            params_card,
        )
        self.chk_rights.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.chk_rights.toggled.connect(self._on_rights_changed)
        params_card.add_widget(self.chk_rights)

        # Dry-run checkbox
        self.chk_dry_run = QCheckBox(
            "🧪 Chế độ chạy thử (Dry-run) - Chạy toàn bộ luồng nhưng không gọi tải lên YouTube thật",
            params_card,
        )
        self.chk_dry_run.setStyleSheet("color: #93c5fd;")
        self.chk_dry_run.toggled.connect(self._on_dry_run_toggled)
        params_card.add_widget(self.chk_dry_run)

        layout.addWidget(params_card)

        # Current Job Summary Card
        summary_card = Card(title="Tóm tắt video chuẩn bị đăng", parent=container)
        s_layout = QVBoxLayout()
        s_layout.setSpacing(8)

        self.lbl_sum_file = QLabel("Tập tin video: Chưa có")
        self.lbl_sum_file.setStyleSheet("color: #cbd5e1;")
        s_layout.addWidget(self.lbl_sum_file)

        self.lbl_sum_title = QLabel("Tiêu đề: Chưa có")
        self.lbl_sum_title.setStyleSheet("font-weight: 600; color: #f8fafc;")
        s_layout.addWidget(self.lbl_sum_title)

        summary_card.add_layout(s_layout)
        layout.addWidget(summary_card)

        # Upload Action Bar
        act_row = QHBoxLayout()
        self.btn_upload = QPushButton("🚀 Tải lên YouTube", container)
        self.btn_upload.setProperty("class", "primaryBtn")
        self.btn_upload.setMinimumHeight(44)
        self.btn_upload.setEnabled(False)  # Locked until prerequisites met
        self.btn_upload.clicked.connect(self._on_upload)
        act_row.addWidget(self.btn_upload, stretch=1)

        self.btn_cancel = QPushButton("Hủy quá trình đăng", container)
        self.btn_cancel.setProperty("class", "dangerBtn")
        self.btn_cancel.setMinimumHeight(44)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        act_row.addWidget(self.btn_cancel)
        layout.addLayout(act_row)

        # Progress bar
        self.progress_bar = QProgressBar(container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Result box
        self.result_box = QFrame(container)
        self.result_box.setStyleSheet(
            "background-color: #064e3b; border: 1px solid #059669; border-radius: 8px; padding: 14px;"
        )
        self.result_box.setVisible(False)
        r_layout = QVBoxLayout(self.result_box)
        r_layout.setSpacing(8)

        self.lbl_result_status = QLabel("✅ Tải lên thành công!")
        self.lbl_result_status.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        r_layout.addWidget(self.lbl_result_status)

        self.lbl_result_link = QLabel("Link: -")
        self.lbl_result_link.setStyleSheet("color: #a7f3d0;")
        r_layout.addWidget(self.lbl_result_link)

        r_btns = QHBoxLayout()
        self.btn_open = QPushButton("Mở xem trên YouTube", self.result_box)
        self.btn_open.clicked.connect(self._on_open_youtube)
        r_btns.addWidget(self.btn_open)

        self.btn_copy = QPushButton("Sao chép liên kết", self.result_box)
        self.btn_copy.clicked.connect(self._on_copy_link)
        r_btns.addWidget(self.btn_copy)
        r_btns.addStretch()
        r_layout.addLayout(r_btns)

        layout.addWidget(self.result_box)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _connect_state(self) -> None:
        self.state.job_changed.connect(self._sync_state)
        self.state.upload_changed.connect(self._on_upload_result)

    def _refresh_channel(self) -> None:
        try:
            ch = self.services.youtube.connect()
            self.lbl_channel_name.setText(f"Kênh: {ch.title}")
            self.lbl_channel_id.setText(f"ID kênh: {ch.id}")
        except Exception as exc:
            self.lbl_channel_name.setText("Kênh: Chưa kết nối")
            self.lbl_channel_id.setText(f"Chi tiết: {exc}")

    def _sync_state(self) -> None:
        if self.state.local_video_path:
            self.lbl_sum_file.setText(f"Tập tin: {self.state.local_video_path.name}")
        else:
            self.lbl_sum_file.setText("Tập tin: Chưa có")

        self.lbl_sum_title.setText(f"Tiêu đề: {self.state.title or '(Trống)'}")

        # Sync privacy
        idx = self.combo_privacy.findData(self.state.privacy)
        if idx >= 0 and self.combo_privacy.currentIndex() != idx:
            self.combo_privacy.blockSignals(True)
            self.combo_privacy.setCurrentIndex(idx)
            self.combo_privacy.blockSignals(False)

        # Sync Made for Kids
        self.radio_kids_yes.blockSignals(True)
        self.radio_kids_no.blockSignals(True)
        if self.state.made_for_kids is True:
            self.radio_kids_yes.setChecked(True)
        elif self.state.made_for_kids is False:
            self.radio_kids_no.setChecked(True)
        else:
            self.kids_group.setExclusive(False)
            self.radio_kids_yes.setChecked(False)
            self.radio_kids_no.setChecked(False)
            self.kids_group.setExclusive(True)
        self.radio_kids_yes.blockSignals(False)
        self.radio_kids_no.blockSignals(False)

        # Sync Rights checkbox
        if self.chk_rights.isChecked() != self.state.rights_confirmed:
            self.chk_rights.blockSignals(True)
            self.chk_rights.setChecked(self.state.rights_confirmed)
            self.chk_rights.blockSignals(False)

        # Sync Dry-run checkbox
        if self.chk_dry_run.isChecked() != self.state.dry_run:
            self.chk_dry_run.blockSignals(True)
            self.chk_dry_run.setChecked(self.state.dry_run)
            self.chk_dry_run.blockSignals(False)

        self._update_upload_button_state()

    @Slot(int)
    def _on_privacy_changed(self, idx: int) -> None:
        val = self.combo_privacy.itemData(idx)
        if val:
            self.state.privacy = val

    @Slot()
    def _on_kids_changed(self) -> None:
        if self.radio_kids_yes.isChecked():
            self.state.made_for_kids = True
        elif self.radio_kids_no.isChecked():
            self.state.made_for_kids = False
        else:
            self.state.made_for_kids = None
        self._update_upload_button_state()

    @Slot(bool)
    def _on_rights_changed(self, checked: bool) -> None:
        self.state.rights_confirmed = checked
        self._update_upload_button_state()

    @Slot(bool)
    def _on_dry_run_toggled(self, checked: bool) -> None:
        self.state.dry_run = checked
        self._update_upload_button_state()

    def _update_upload_button_state(self) -> None:
        title = self.state.title.strip()
        title_ok = 0 < len(title) <= 100 and "<" not in title and ">" not in title
        kids_ok = self.radio_kids_yes.isChecked() or self.radio_kids_no.isChecked()
        rights_ok = self.chk_rights.isChecked()
        has_video = bool(self.state.local_video_path)
        self.btn_upload.setEnabled(title_ok and kids_ok and rights_ok and has_video)
        if self.state.dry_run:
            self.btn_upload.setText("🧪 Chạy thử đăng YouTube (Dry-run)")
        else:
            self.btn_upload.setText("🚀 Tải lên YouTube")

    @Slot()
    def _on_upload(self) -> None:
        can, reason = self.state.can_upload()
        if not can:
            QMessageBox.warning(self, "Chưa đủ điều kiện đăng", reason)
            return

        try:
            req = self.state.build_upload_request()
            channel = self.services.youtube.get_channel()
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi kiểm tra", str(exc))
            return

        # Explicit confirmation dialog per requirement
        dialog = UploadConfirmDialog(
            req, channel.title, channel.id, self, dry_run=self.state.dry_run
        )
        if dialog.exec() != UploadConfirmDialog.DialogCode.Accepted:
            return  # Cancelled

        if not self.state.dry_run and hasattr(self.services.youtube, "confirm_upload"):
            self.services.youtube.confirm_upload(
                req, made_for_kids=req.made_for_kids, channel_id=channel.id
            )
        self.btn_upload.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)

        worker = UploadYouTubeWorker(self.services.youtube, req, dry_run=self.state.dry_run)
        self._active_upload_worker = worker
        worker.signals.progress.connect(lambda p: self.progress_bar.setValue(int(p * 100)))
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(self._on_cancelled)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_finished(self, res: UploadResult) -> None:
        self.progress_bar.setValue(100)
        self.btn_upload.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self._active_upload_worker = None
        self.state.set_upload_result(res)

        if self.state.dry_run:
            return
        try:
            meta = self.state.meta
            download = self.state.download_result
            self.services.history.add({
                "video_id": meta.video_id if meta else "",
                "url": meta.url if meta else "",
                "title": meta.title if meta else self.state.title,
                "youtube_title": self.state.title,
                "youtube_description": self.state.description,
                "youtube_video_id": res.video_id,
                "youtube_url": res.url,
                "youtube_channel_id": res.channel_id,
                "local_mp4_path": str(self.state.local_video_path),
                "sha256": download.sha256 if download else "",
                "status": self.state.status,
                "privacy_status": self.state.privacy,
                "rights_confirmed": self.state.rights_confirmed,
            })
        except Exception:
            QMessageBox.warning(self, "Lịch sử", "Video đã đăng nhưng không lưu được lịch sử.")

    @Slot()
    def _on_cancel(self) -> None:
        if self._active_upload_worker:
            self._active_upload_worker.cancel()

    @Slot()
    def _on_cancelled(self) -> None:
        self.btn_upload.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.progress_bar.setVisible(False)
        self._active_upload_worker = None
        QMessageBox.information(self, "Đã hủy", "Đã hủy quá trình đăng video.")

    @Slot(str)
    def _on_error(self, err: str) -> None:
        self.btn_upload.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.progress_bar.setVisible(False)
        self._active_upload_worker = None
        QMessageBox.critical(self, "Lỗi đăng video", f"Tải lên thất bại: {err}")

    @Slot(object)
    def _on_upload_result(self, res: Optional[UploadResult]) -> None:
        if res:
            self.result_box.setVisible(True)
            self.lbl_result_status.setText("✅ Video đã đăng tải thành công!")
            self.lbl_result_link.setText(f"Liên kết: {res.url}")

    @Slot()
    def _on_open_youtube(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            QDesktopServices.openUrl(QUrl(self.state.upload_result.url))

    @Slot()
    def _on_copy_link(self) -> None:
        if self.state.upload_result and self.state.upload_result.url:
            QGuiApplication.clipboard().setText(self.state.upload_result.url)
            QMessageBox.information(self, "Đã sao chép", "Đã sao chép link YouTube.")

