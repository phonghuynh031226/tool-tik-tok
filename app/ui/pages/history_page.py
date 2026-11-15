"""History & Scheduling page: Past video records and Scheduled video tracker."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.contracts import HistoryRecord, JobStatus, UploadResult
from app.ui import tokens
from app.ui.components import AppButton, Card, StatusBadge, ToastManager
from app.ui.icons import get_icon
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import SyncScheduledWorker


class HistoryPage(QWidget):
    """History and Scheduling view with 2 tabs: History records and Scheduled uploads."""

    navigate_requested = Signal(int)  # Emit target page index to MainWindow

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
        self._current_records: list[dict] = []
        self._scheduled_records: list[dict] = []

        self._init_ui()
        self.refresh_history()
        self.refresh_scheduled()

        # Timer to update countdown every 5 seconds
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdowns)
        self._countdown_timer.start(5000)

    def _notify(self, ntype: str, title: str, message: str) -> None:
        toast = ToastManager.instance()
        if toast:
            getattr(toast, ntype, toast.info)(title, message)

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(12)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_MD}px; background-color: {tokens.BG_APP}; }}"
            f"QTabBar::tab {{ background-color: {tokens.BG_CARD}; color: {tokens.TEXT_SECONDARY}; "
            f"padding: 10px 20px; font-weight: 600; font-size: 13px; "
            f"border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }}"
            f"QTabBar::tab:selected {{ background-color: {tokens.BG_CARD_HOVER}; "
            f"color: {tokens.COLOR_PRIMARY}; border-bottom: 2px solid {tokens.COLOR_PRIMARY}; }}"
            f"QTabBar::tab:hover {{ background-color: {tokens.BG_CARD_HOVER}; color: {tokens.TEXT_PRIMARY}; }}"
        )

        # Tab 1: History
        self.tab_history = self._create_history_tab()
        self.tab_widget.addTab(self.tab_history, get_icon("nav_history"), "Lịch sử tác vụ")

        # Tab 2: Scheduled Uploads
        self.tab_scheduled = self._create_scheduled_tab()
        self.tab_widget.addTab(self.tab_scheduled, get_icon("clock"), "Lịch đăng video")

        outer_layout.addWidget(self.tab_widget)

    # =========================================================================
    # TAB 1: HISTORY RECORDS
    # =========================================================================
    def _create_history_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        head_info = QVBoxLayout()
        header = QLabel("Lịch Sử Tải & Xuất Bản Video", container)
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        head_info.addWidget(header)

        sub = QLabel(
            "Tra cứu các video đã được xử lý, mở thư mục MP4, xem liên kết YouTube hoặc tiếp tục tác vụ dở dang.",
            container,
        )
        sub.setProperty("class", "hintLabel")
        head_info.addWidget(sub)
        header_row.addLayout(head_info, stretch=1)

        self.btn_export_csv = AppButton("Xuất CSV", variant="secondary", icon_name="export", parent=container)
        self.btn_export_csv.clicked.connect(self._export_csv)
        header_row.addWidget(self.btn_export_csv)
        layout.addLayout(header_row)

        # Filter Card
        filter_card = Card(parent=container)
        f_layout = QHBoxLayout()
        f_layout.setSpacing(10)

        self.input_search = QLineEdit(filter_card)
        self.input_search.setPlaceholderText("Tìm kiếm theo ID video, tiêu đề, URL...")
        self.input_search.textChanged.connect(self._on_search_changed)
        f_layout.addWidget(self.input_search, stretch=1)

        self.combo_status = QComboBox(filter_card)
        self.combo_status.addItem("Tất cả trạng thái", None)
        for s in JobStatus:
            self.combo_status.addItem(s.value, s)
        self.combo_status.currentIndexChanged.connect(self.refresh_history)
        f_layout.addWidget(self.combo_status)

        self.btn_refresh = AppButton("Làm mới", variant="ghost", icon_name="refresh", parent=filter_card)
        self.btn_refresh.clicked.connect(self.refresh_history)
        f_layout.addWidget(self.btn_refresh)

        filter_card.add_layout(f_layout)
        layout.addWidget(filter_card)

        # History Table
        self.table = QTableWidget(container)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Mã ID", "Tiêu đề video", "Trạng thái", "Chế độ", "Hành động"
        ])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 300)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        return container

    # =========================================================================
    # TAB 2: SCHEDULED UPLOADS
    # =========================================================================
    def _create_scheduled_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header
        h_row = QHBoxLayout()
        h_info = QVBoxLayout()
        h_title = QLabel("Lịch Đăng Video Hẹn Giờ (YouTube Scheduled)", container)
        h_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        h_info.addWidget(h_title)

        h_sub = QLabel(
            "Theo dõi thời gian công khai video theo múi giờ máy tính. Bấm 'Đồng bộ trạng thái' để kiểm tra xem video đã được phát hành chưa.",
            container,
        )
        h_sub.setProperty("class", "hintLabel")
        h_info.addWidget(h_sub)
        h_row.addLayout(h_info, stretch=1)

        self.btn_sync_scheduled = AppButton("Đồng bộ trạng thái", variant="primary", icon_name="refresh", parent=container)
        self.btn_sync_scheduled.clicked.connect(self._on_sync_scheduled_clicked)
        h_row.addWidget(self.btn_sync_scheduled)

        self.btn_refresh_scheduled = AppButton("Làm mới", variant="ghost", icon_name="refresh", parent=container)
        self.btn_refresh_scheduled.clicked.connect(self.refresh_scheduled)
        h_row.addWidget(self.btn_refresh_scheduled)
        layout.addLayout(h_row)

        self.prog_sync = QProgressBar(container)
        self.prog_sync.setRange(0, 0)
        self.prog_sync.setFixedHeight(3)
        self.prog_sync.setTextVisible(False)
        self.prog_sync.setVisible(False)
        layout.addWidget(self.prog_sync)

        # Scheduled Table
        self.tbl_scheduled = QTableWidget(container)
        self.tbl_scheduled.setColumnCount(6)
        self.tbl_scheduled.setHorizontalHeaderLabels([
            "Mã Video", "Tiêu đề video", "Kênh YouTube", "Giờ công khai (máy tính)", "Thời gian còn lại", "Trạng thái"
        ])
        s_head = self.tbl_scheduled.horizontalHeader()
        s_head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        s_head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        s_head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        s_head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        s_head.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        s_head.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_scheduled.verticalHeader().setVisible(False)
        self.tbl_scheduled.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_scheduled.setAlternatingRowColors(True)
        layout.addWidget(self.tbl_scheduled)

        return container

    # =========================================================================
    # HISTORY LOGIC
    # =========================================================================
    @Slot()
    def refresh_history(self) -> None:
        query = self.input_search.text().strip()
        status_filter = self.combo_status.currentData()

        try:
            if query:
                records = self.services.history.search(query)
            else:
                records = self.services.history.list(status=status_filter)
        except Exception:
            records = []

        records = [dict(record) for record in records]
        for record in records:
            simulated = record.get("dry_run") is True or any(
                str(record.get(key) or "").startswith("dry-run") for key in ("video_id", "youtube_video_id")
            )
            if simulated:
                record.update(status="DRY_RUN", processing_status="DRY_RUN", youtube_video_id=None, youtube_url=None, url="")
        self._current_records = list(records)

        status_text_map = {
            "NEW": "Mới tạo",
            "METADATA_OK": "Đã lấy thông tin",
            "DOWNLOADED": "Đã tải về",
            "CONTENT_READY": "Nội dung sẵn sàng",
            "UPLOADING": "Đang tải lên...",
            "UPLOADED": "Đã xuất bản",
            "SCHEDULED": "Đã hẹn giờ",
            "DRY_RUN": "Chạy thử",
            "FAILED": "Thất bại",
            "CANCELLED": "Đã hủy",
        }

        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            source_id = str(rec.get("tiktok_video_id") or rec.get("video_id") or "")
            source_path = rec.get("local_mp4_path") or rec.get("path") or rec.get("local_video_path")
            if source_id and not source_id.startswith(("dry-run", "local-")):
                vid_id = source_id
            elif source_path:
                vid_id = Path(str(source_path).replace("\\", "/")).name
            else:
                vid_id = "—"

            title = str(rec.get("title") or "Không tiêu đề")
            raw_status = rec.get("status")
            status_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status or "NEW")
            status_display = status_text_map.get(status_val, status_val)
            privacy = str(rec.get("privacy") or "private")
            url = str(rec.get("url") or rec.get("youtube_url") or "")
            path_str = str(rec.get("path") or rec.get("local_video_path") or "")

            item_id = QTableWidgetItem(vid_id)
            item_id.setFlags(item_id.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_id)

            item_title = QTableWidgetItem(title)
            item_title.setFlags(item_title.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, item_title)

            item_status = QTableWidgetItem(status_display)
            item_status.setFlags(item_status.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, item_status)

            item_priv = QTableWidgetItem(privacy)
            item_priv.setFlags(item_priv.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, item_priv)

            # Action cell
            action_widget = QWidget()
            a_layout = QHBoxLayout(action_widget)
            a_layout.setContentsMargins(4, 2, 4, 2)
            a_layout.setSpacing(6)

            btn_resume = AppButton("Tiếp tục", variant="primary", icon_name="play")
            btn_resume.setEnabled(status_val != "DRY_RUN")
            btn_resume.setFixedHeight(28)
            btn_resume.clicked.connect(lambda _, r=rec: self._resume_job(r))
            a_layout.addWidget(btn_resume)

            btn_folder = AppButton("Thư mục", variant="secondary", icon_name="folder")
            btn_folder.setFixedHeight(28)
            btn_folder.clicked.connect(lambda _, p=path_str: self._open_mp4_folder(p))
            a_layout.addWidget(btn_folder)

            if url:
                btn_open = AppButton("YouTube", variant="secondary", icon_name="link")
                btn_open.setFixedHeight(28)
                btn_open.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                a_layout.addWidget(btn_open)

            self.table.setCellWidget(row, 4, action_widget)

    def _open_mp4_folder(self, path_str: str) -> None:
        p = Path(path_str) if path_str else None
        if p and p.exists():
            folder = p.parent if p.is_file() else p
        else:
            folder = Path(".tmp/downloads").resolve()
            folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _resume_job(self, rec: dict) -> None:
        self.state.load_from_record(rec)
        self.navigate_requested.emit(0)
        self._notify("info", "Tiếp tục tác vụ", f"Đã nạp tác vụ '{self.state.title or rec.get('video_id')}' vào Tổng quan.")

    def _export_csv(self) -> None:
        if not self._current_records:
            self._notify("warning", "Không có dữ liệu", "Không có bản ghi lịch sử nào để xuất CSV.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Xuất Lịch Sử Ra Tệp CSV", "history_export.csv", "CSV Files (*.csv);;Tất cả tập tin (*.*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Mã Video", "Tiêu đề", "URL", "Trạng thái",
                    "Chế độ hiển thị", "Đường dẫn file", "Hashtags", "Tags"
                ])
                for rec in self._current_records:
                    writer.writerow([
                        rec.get("id", ""),
                        rec.get("video_id", ""),
                        rec.get("title", ""),
                        rec.get("url", ""),
                        rec.get("status", ""),
                        rec.get("privacy", ""),
                        rec.get("path") or rec.get("local_video_path") or "",
                        " ".join(rec.get("hashtags", [])),
                        ", ".join(rec.get("tags", [])),
                    ])
            self._notify("success", "Xuất CSV thành công", f"Đã xuất {len(self._current_records)} bản ghi vào file.")
            QMessageBox.information(
                self,
                "Xuất CSV thành công",
                f"Đã xuất thành công {len(self._current_records)} bản ghi vào:\n{file_path}",
            )
        except Exception as exc:
            self._notify("error", "Lỗi xuất CSV", f"Không thể ghi file CSV: {exc}")
            QMessageBox.critical(self, "Lỗi xuất CSV", f"Không thể ghi file CSV: {exc}")

    @Slot(str)
    def _on_search_changed(self, text: str) -> None:
        self.refresh_history()

    # =========================================================================
    # SCHEDULED LOGIC
    # =========================================================================
    @Slot()
    def refresh_scheduled(self) -> None:
        try:
            records = self.services.history.list_scheduled()
        except Exception:
            records = []

        self._scheduled_records = [dict(r) for r in records]
        self._render_scheduled(self._scheduled_records)

    def _render_scheduled(self, records: list[dict]) -> None:
        self.tbl_scheduled.setRowCount(len(records))
        now_utc = datetime.now(timezone.utc)

        for row, rec in enumerate(records):
            vid_id = str(rec.get("video_id") or rec.get("tiktok_video_id") or "—")
            title = str(rec.get("title") or "Không tiêu đề")
            channel = str(rec.get("channel_title") or rec.get("channel_id") or "Kênh mặc định")

            # Publish at
            pub_at = rec.get("publish_at")
            if isinstance(pub_at, datetime):
                # Convert to machine local time
                local_dt = pub_at.astimezone()
                time_str = local_dt.strftime("%d/%m/%Y %H:%M:%S")

                if pub_at <= now_utc:
                    cd_str = "Đã đến giờ"
                    is_due = True
                else:
                    diff = pub_at - now_utc
                    sec = int(diff.total_seconds())
                    hrs = sec // 3600
                    mins = (sec % 3600) // 60
                    cd_str = f"Còn {hrs}h {mins:02d}m"
                    is_due = False
            else:
                time_str = "Chưa xác định"
                cd_str = "—"
                is_due = False

            # Status
            raw_st = rec.get("status")
            st_val = raw_st.value if hasattr(raw_st, "value") else str(raw_st or "")
            if st_val == "UPLOADED":
                status_label = "Đã công khai"
                badge_type = "success"
            elif is_due:
                status_label = "Đến giờ công khai"
                badge_type = "info"
            else:
                status_label = "Chờ công khai"
                badge_type = "warning"

            self.tbl_scheduled.setItem(row, 0, QTableWidgetItem(vid_id))
            self.tbl_scheduled.setItem(row, 1, QTableWidgetItem(title))
            self.tbl_scheduled.setItem(row, 2, QTableWidgetItem(channel))
            self.tbl_scheduled.setItem(row, 3, QTableWidgetItem(time_str))
            self.tbl_scheduled.setItem(row, 4, QTableWidgetItem(cd_str))

            badge = StatusBadge(status=status_label, badge_type=badge_type)
            self.tbl_scheduled.setCellWidget(row, 5, badge)

    @Slot()
    def _update_countdowns(self) -> None:
        if self._scheduled_records:
            self._render_scheduled(self._scheduled_records)

    @Slot()
    def _on_sync_scheduled_clicked(self) -> None:
        self.prog_sync.setVisible(True)
        self.btn_sync_scheduled.setEnabled(False)

        worker = SyncScheduledWorker(self.services.youtube, self.services.history)
        worker.signals.finished.connect(self._on_sync_finished)
        worker.signals.error.connect(self._on_sync_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_sync_finished(self, published: list[UploadResult]) -> None:
        self.prog_sync.setVisible(False)
        self.btn_sync_scheduled.setEnabled(True)
        self.refresh_scheduled()
        self.refresh_history()

        count = len(published)
        if count > 0:
            self._notify("success", "Đồng bộ thành công", f"Đã có {count} video được YouTube chính thức công khai!")
        else:
            self._notify("info", "Đồng bộ hoàn tất", "Không có video nào chuyển trạng thái công khai.")

    @Slot(str)
    def _on_sync_error(self, err: str) -> None:
        self.prog_sync.setVisible(False)
        self.btn_sync_scheduled.setEnabled(True)
        self._notify("error", "Lỗi đồng bộ lịch đăng", err)


HistorySchedulePage = HistoryPage
