"""History page displaying past video processing and upload records with export and resume."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from app.contracts import JobStatus
from app.ui.components import Card
from app.ui.services import ServiceContainer
from app.ui.state import JobState


class HistoryPage(QWidget):
    """History and log view for all past processed jobs with CSV export and job resumption."""

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
        self._current_records: list[dict] = []

        self._init_ui()
        self.refresh_history()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        header = QLabel("Lịch Sử Tải & Xuất Bản Video", self)
        header.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        header_row.addWidget(header)
        header_row.addStretch()

        self.btn_export_csv = QPushButton("📥 Xuất CSV", self)
        self.btn_export_csv.clicked.connect(self._export_csv)
        header_row.addWidget(self.btn_export_csv)
        layout.addLayout(header_row)

        sub = QLabel(
            "Tra cứu các video đã được tải từ TikTok và đăng lên YouTube, mở thư mục MP4, xem link hoặc tiếp tục job dở dang.",
            self,
        )
        sub.setProperty("class", "hintLabel")
        layout.addWidget(sub)

        # Filter bar
        filter_card = Card(parent=self)
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

        self.btn_refresh = QPushButton("Làm mới danh sách", filter_card)
        self.btn_refresh.clicked.connect(self.refresh_history)
        f_layout.addWidget(self.btn_refresh)

        filter_card.add_layout(f_layout)
        layout.addWidget(filter_card)

        # History Table
        self.table = QTableWidget(self)
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
        layout.addWidget(self.table)

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

        # Older versions persisted simulated UploadResult values. Do not display
        # them as published or expose their invented URLs; leave stored data intact.
        records = [dict(record) for record in records]
        for record in records:
            simulated = record.get('dry_run') is True or any(
                str(record.get(key) or '').startswith('dry-run') for key in ('video_id', 'youtube_video_id'))
            if simulated:
                record.update(status='DRY_RUN', processing_status='DRY_RUN', youtube_video_id=None, youtube_url=None, url='')
        self._current_records = list(records)

        status_text_map = {
            "NEW": "Mới tạo",
            "METADATA_OK": "Đã lấy thông tin",
            "DOWNLOADED": "Đã tải về",
            "CONTENT_READY": "Nội dung sẵn sàng",
            "UPLOADING": "Đang tải lên...",
            "UPLOADED": "Đã xuất bản",
            "DRY_RUN": "Chạy thử",
            "FAILED": "Thất bại",
            "CANCELLED": "Đã hủy",
        }

        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            vid_id = str(rec.get("video_id") or rec.get("id") or "-")
            title = str(rec.get("title") or "Không tiêu đề")
            raw_status = rec.get("status")
            status_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status or "NEW")
            status_display = status_text_map.get(status_val, status_val)
            privacy = str(rec.get("privacy") or "private")
            url = str(rec.get("url") or "")
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

            # Action cell with 4 buttons: Mở link, Mở thư mục, Tiếp tục, Sao chép
            action_widget = QWidget()
            a_layout = QHBoxLayout(action_widget)
            a_layout.setContentsMargins(4, 2, 4, 2)
            a_layout.setSpacing(4)

            # 1. Tiếp tục job dở dang
            btn_resume = QPushButton("Tiếp tục")
            btn_resume.setEnabled(status_val != 'DRY_RUN')
            btn_resume.setProperty("class", "primaryBtn")
            btn_resume.setFixedHeight(28)
            btn_resume.setStyleSheet("padding: 2px 6px; font-size: 11px;")
            btn_resume.clicked.connect(lambda _, r=rec: self._resume_job(r))
            a_layout.addWidget(btn_resume)

            # 2. Mở thư mục MP4
            btn_folder = QPushButton("Thư mục")
            btn_folder.setFixedHeight(28)
            btn_folder.setStyleSheet("padding: 2px 6px; font-size: 11px;")
            btn_folder.clicked.connect(lambda _, p=path_str: self._open_mp4_folder(p))
            a_layout.addWidget(btn_folder)

            # 3. Mở link YouTube (nếu có)
            if url:
                btn_open = QPushButton("YouTube")
                btn_open.setFixedHeight(28)
                btn_open.setStyleSheet("padding: 2px 6px; font-size: 11px;")
                btn_open.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                a_layout.addWidget(btn_open)

            self.table.setCellWidget(row, 4, action_widget)

    def _open_mp4_folder(self, path_str: str) -> None:
        """Open folder containing MP4 in system file explorer."""
        p = Path(path_str) if path_str else None
        if p and p.exists():
            folder = p.parent if p.is_file() else p
        else:
            folder = Path(".tmp/downloads").resolve()
            folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _resume_job(self, rec: dict) -> None:
        """Resume incomplete or existing job by loading into JobState and navigating."""
        self.state.load_from_record(rec)
        status = self.state.status

        # Navigate based on JobStatus per requirement
        if status in (JobStatus.NEW, JobStatus.FAILED):
            target_page = 0  # Dashboard / TikTok Step 1
            msg = f"Đã nạp tác vụ '{self.state.title or rec.get('video_id')}'. Bạn có thể tiếp tục tải video."
        elif status == JobStatus.METADATA_OK:
            target_page = 0  # Dashboard Step 1 / 2
            msg = f"Đã nạp metadata video '{self.state.title}'. Bạn có thể tiếp tục tải video."
        elif status == JobStatus.DOWNLOADED:
            target_page = 0  # Dashboard Step 3 (AI)
            msg = f"Video đã có sẵn. Chuyển sang bước tạo nội dung AI."
        elif status in (JobStatus.CONTENT_READY, JobStatus.UPLOADING, JobStatus.CANCELLED):
            target_page = 0  # Dashboard Step 4 (YouTube)
            msg = f"Nội dung đã sẵn sàng. Chuyển sang bước đăng tải YouTube."
        elif status == JobStatus.UPLOADED:
            target_page = 0  # Dashboard
            msg = f"Tác vụ này đã xuất bản hoàn tất trước đó."
        else:
            target_page = 0
            msg = "Đã nạp dữ liệu tác vụ vào Dashboard."

        self.navigate_requested.emit(target_page)
        QMessageBox.information(self, "Tiếp tục tác vụ", msg)

    def _export_csv(self) -> None:
        """Export current history records to CSV with UTF-8 BOM."""
        if not self._current_records:
            QMessageBox.warning(self, "Không có dữ liệu", "Không có bản ghi lịch sử nào để xuất CSV.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất Lịch Sử Ra Tệp CSV",
            "history_export.csv",
            "CSV Files (*.csv);;Tất cả tập tin (*.*)",
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
            QMessageBox.information(
                self,
                "Xuất CSV thành công",
                f"Đã xuất thành công {len(self._current_records)} bản ghi vào:\n{file_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xuất CSV", f"Không thể ghi file CSV: {exc}")

    @Slot(str)
    def _on_search_changed(self, text: str) -> None:
        self.refresh_history()
