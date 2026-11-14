"""Upload confirmation dialog to protect against accidental uploads."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.contracts import UploadRequest


class UploadConfirmDialog(QDialog):
    """Explicit confirmation dialog showing destination channel, title, and privacy."""

    def __init__(
        self,
        request: UploadRequest,
        channel_title: str,
        channel_id: str,
        parent: Optional[QWidget] = None,
        dry_run: bool = False,
    ) -> None:
        super().__init__(parent)
        self.dry_run = dry_run
        self.setWindowTitle(
            "🧪 [DRY-RUN] Xác nhận chạy thử" if dry_run else "Xác nhận tải video lên YouTube"
        )
        self.setFixedWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header Title
        title_text = "🧪 Sẵn sàng chạy thử quy trình (Dry-run)?" if dry_run else "🚀 Sẵn sàng tải lên YouTube?"
        title_label = QLabel(title_text)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        layout.addWidget(title_label)

        sub_text = (
            "Chế độ chạy thử đang BẬT: Hệ thống sẽ thực hiện kiểm tra và mô phỏng luồng mà KHÔNG tải video lên kênh thật."
            if dry_run
            else "Vui lòng kiểm tra kỹ thông tin bên dưới trước khi bắt đầu tải video lên kênh của bạn."
        )
        sub_label = QLabel(sub_text)
        sub_label.setWordWrap(True)
        sub_label.setProperty("class", "hintLabel")
        layout.addWidget(sub_label)

        # Info Box Frame
        info_frame = QFrame(self)
        info_frame.setProperty("class", "card")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(10)

        # Rows
        if dry_run:
            self._add_row(info_layout, "Chế độ tác vụ:", "🧪 CHẠY THỬ (DRY-RUN) - Không gọi upload")
        self._add_row(info_layout, "Kênh đích:", f"{channel_title} ({channel_id})")
        self._add_row(info_layout, "Tiêu đề:", request.title)

        privacy_vi = {
            "private": "Riêng tư (Chỉ bạn xem được - Khuyên dùng)",
            "unlisted": "Không công khai (Chỉ người có link mới xem)",
            "public": "Công khai (Mọi người đều tìm thấy)",
        }.get(request.privacy, request.privacy)
        self._add_row(info_layout, "Chế độ hiển thị:", privacy_vi)

        kids_vi = "Có (Dành cho trẻ em)" if request.made_for_kids else "Không (Không dành cho trẻ em)"
        self._add_row(info_layout, "Đối tượng người xem:", kids_vi)
        self._add_row(info_layout, "Tập tin:", request.path.name)

        layout.addWidget(info_frame)

        self.lbl_privacy_warning = QLabel(self)
        self.lbl_privacy_warning.setWordWrap(True)
        self.lbl_privacy_warning.setStyleSheet('background:#7f1d1d;color:#fef08a;padding:12px;font-weight:bold;')
        if request.privacy in {'public', 'unlisted'}:
            self.lbl_privacy_warning.setText('⚠ ' + request.privacy.upper() + ': Video sẽ không còn ở chế độ Riêng tư. ' +
                ('Mọi người có thể xem và tìm thấy video.' if request.privacy == 'public' else 'Bất kỳ ai có liên kết đều có thể xem và chia sẻ.'))
        else:
            self.lbl_privacy_warning.hide()
        layout.addWidget(self.lbl_privacy_warning)

        # Warning / Info text
        if dry_run:
            warn_box = QLabel(
                "🧪 Lưu ý: Đây là chế độ chạy thử an toàn. Quy trình sẽ xác thực toàn bộ dữ liệu, "
                "mô phỏng tiến trình tải lên nhưng sẽ không thực sự tạo video trên kênh YouTube của bạn."
            )
            warn_box.setStyleSheet(
                "color: #60a5fa; font-size: 11px; padding: 10px; "
                "background-color: #0f1d38; border: 1px solid #1e3a8a; border-radius: 6px;"
            )
        else:
            warn_box = QLabel(
                "⚠️ Lưu ý: Thao tác này sẽ tải video trực tiếp lên kênh YouTube của bạn. "
                "Bạn phải đảm bảo đã kiểm tra nội dung và có toàn quyền sử dụng hợp pháp video này."
            )
            warn_box.setStyleSheet(
                "color: #fbbf24; font-size: 11px; padding: 10px; "
                "background-color: #261f0d; border: 1px solid #78350f; border-radius: 6px;"
            )
        warn_box.setWordWrap(True)
        layout.addWidget(warn_box)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Hủy bỏ", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        confirm_btn_text = "Xác nhận chạy thử (Dry-run)" if dry_run else "Xác nhận và Tải lên"
        self.btn_confirm = QPushButton(confirm_btn_text, self)
        self.btn_confirm.setProperty("class", "primaryBtn")
        self.btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)

    def _add_row(self, layout: QVBoxLayout, label: str, value: str) -> None:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #94a3b8; font-weight: 600; min-width: 130px;")
        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet("color: #f8fafc;")
        row.addWidget(lbl)
        row.addWidget(val, stretch=1)
        layout.addLayout(row)

