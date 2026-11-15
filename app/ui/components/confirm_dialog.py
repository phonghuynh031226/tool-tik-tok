"""Confirmation dialogs styled consistently with the modern design system."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.contracts import UploadRequest
from app.ui import icons, tokens
from app.ui.components.buttons import AppButton


class ConfirmDialog(QDialog):
    """General purpose confirmation dialog with consistent styling."""

    def __init__(
        self,
        title: str,
        message: str,
        confirm_text: str = "Xác nhận",
        cancel_text: str = "Hủy bỏ",
        is_danger: bool = False,
        icon_name: str = "warning",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG
        )
        layout.setSpacing(tokens.SPACE_MD)

        header_row = QHBoxLayout()
        header_row.setSpacing(tokens.SPACE_MD)

        icon_color = tokens.DANGER if is_danger else tokens.WARNING
        icon_lbl = QLabel(self)
        icon_lbl.setPixmap(icons.get_colored_icon(icon_name, icon_color).pixmap(28, 28))
        header_row.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(tokens.SPACE_XS)

        title_lbl = QLabel(title, self)
        title_lbl.setStyleSheet(
            f"font-size: {tokens.FONT_SIZE_LG}px; font-weight: 700; color: {tokens.TEXT_PRIMARY};"
        )
        text_box.addWidget(title_lbl)

        msg_lbl = QLabel(message, self)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_BASE}px;")
        text_box.addWidget(msg_lbl)

        header_row.addLayout(text_box, stretch=1)
        layout.addLayout(header_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(tokens.SPACE_SM)
        btn_row.addStretch()

        self.btn_cancel = AppButton(cancel_text, variant="secondary", parent=self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        variant = "danger" if is_danger else "primary"
        self.btn_confirm = AppButton(confirm_text, variant=variant, parent=self)
        self.btn_confirm.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_confirm)

        layout.addLayout(btn_row)


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
            "[DRY-RUN] Xác nhận chạy thử" if dry_run else "Xác nhận tải video lên YouTube"
        )
        self.setFixedWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG, tokens.SPACE_LG
        )
        layout.setSpacing(tokens.SPACE_MD)

        # Header Title
        title_row = QHBoxLayout()
        title_row.setSpacing(tokens.SPACE_SM)

        header_icon = QLabel(self)
        h_icon_name = "test" if dry_run else "upload"
        h_icon_color = tokens.INFO if dry_run else tokens.PRIMARY
        header_icon.setPixmap(icons.get_colored_icon(h_icon_name, h_icon_color).pixmap(24, 24))
        title_row.addWidget(header_icon)

        title_text = "Sẵn sàng chạy thử quy trình (Dry-run)?" if dry_run else "Sẵn sàng tải lên YouTube?"
        title_label = QLabel(title_text)
        title_label.setStyleSheet(f"font-size: {tokens.FONT_SIZE_XL}px; font-weight: 700; color: {tokens.TEXT_INVERTED};")
        title_row.addWidget(title_label, stretch=1)
        layout.addLayout(title_row)

        sub_text = (
            "Chế độ chạy thử đang BẬT: Hệ thống sẽ thực hiện kiểm tra và mô phỏng luồng mà KHÔNG tải video lên kênh thật."
            if dry_run
            else "Vui lòng kiểm tra kỹ thông tin bên dưới trước khi bắt đầu tải video lên kênh của bạn."
        )
        sub_label = QLabel(sub_text)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_SM}px;")
        layout.addWidget(sub_label)

        # Info Box Frame
        info_frame = QFrame(self)
        info_frame.setProperty("class", "card")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(tokens.SPACE_SM)

        # Rows
        if dry_run:
            self._add_row(info_layout, "Chế độ tác vụ:", "CHẠY THỬ (DRY-RUN) - Không gọi upload")
        self._add_row(info_layout, "Kênh đích:", f"{channel_title} ({channel_id})")
        self._add_row(info_layout, "Tiêu đề:", request.title)

        if request.publish_at is not None:
            local_dt = request.publish_at.astimezone()
            time_str = local_dt.strftime("%d/%m/%Y %H:%M")
            self._add_row(info_layout, "Thời điểm xuất bản:", f"Hẹn công khai lúc {time_str} (giờ máy tính)")
            self._add_row(info_layout, "Chế độ ban đầu:", "Riêng tư (YouTube tự động công khai khi đến giờ)")
        else:
            privacy_vi = {
                "private": "Riêng tư (Chỉ bạn xem được - Khuyên dùng)",
                "unlisted": "Không công khai (Chỉ người có link mới xem)",
                "public": "Công khai (Mọi người đều tìm thấy)",
            }.get(request.privacy, request.privacy)
            self._add_row(info_layout, "Thời điểm xuất bản:", f"Đăng ngay, chế độ: {privacy_vi}")
            self._add_row(info_layout, "Chế độ hiển thị:", privacy_vi)

        kids_vi = "Có (Dành cho trẻ em)" if request.made_for_kids else "Không (Không dành cho trẻ em)"
        self._add_row(info_layout, "Đối tượng người xem:", kids_vi)
        self._add_row(info_layout, "Tập tin:", request.path.name)

        layout.addWidget(info_frame)

        self.lbl_privacy_warning = QLabel(self)
        self.lbl_privacy_warning.setWordWrap(True)
        self.lbl_privacy_warning.setStyleSheet(
            f"background-color: {tokens.DANGER_BG}; color: #fef08a; padding: 12px; font-weight: bold; "
            f"border: 1px solid {tokens.DANGER_BORDER}; border-radius: {tokens.RADIUS_MD}px;"
        )
        if request.privacy in {'public', 'unlisted'} and request.publish_at is None:
            self.lbl_privacy_warning.setText(
                request.privacy.upper() + ': Video sẽ không còn ở chế độ Riêng tư. ' +
                ('Mọi người có thể xem và tìm thấy video.' if request.privacy == 'public' else 'Bất kỳ ai có liên kết đều có thể xem và chia sẻ.')
            )
            self.lbl_privacy_warning.show()
        elif request.publish_at is not None:
            local_dt = request.publish_at.astimezone()
            self.lbl_privacy_warning.setText(
                f"LÊN LỊCH PHÁT HÀNH: Video sẽ tải lên ở chế độ Riêng tư, sau đó YouTube sẽ tự động công khai vào lúc {local_dt.strftime('%d/%m/%Y %H:%M')} (giờ máy tính). Bạn không cần mở ứng dụng hay bật máy khi đến giờ hẹn."
            )
            self.lbl_privacy_warning.setStyleSheet(
                f"background-color: {tokens.INFO_BG}; color: #bae6fd; padding: 12px; font-weight: bold; "
                f"border: 1px solid {tokens.INFO_BORDER}; border-radius: {tokens.RADIUS_MD}px;"
            )
            self.lbl_privacy_warning.show()
        else:
            self.lbl_privacy_warning.hide()
        layout.addWidget(self.lbl_privacy_warning)

        # Warning / Info text
        if dry_run:
            warn_box = QLabel(
                "Lưu ý: Đây là chế độ chạy thử an toàn. Quy trình sẽ xác thực toàn bộ dữ liệu, "
                "mô phỏng tiến trình tải lên nhưng sẽ không thực sự tạo video trên kênh YouTube của bạn."
            )
            warn_box.setStyleSheet(
                f"color: #93c5fd; font-size: {tokens.FONT_SIZE_SM}px; padding: 10px; "
                f"background-color: {tokens.INFO_BG}; border: 1px solid {tokens.INFO_BORDER}; border-radius: {tokens.RADIUS_MD}px;"
            )
        else:
            warn_box = QLabel(
                "Lưu ý: Thao tác này sẽ tải video trực tiếp lên kênh YouTube của bạn. "
                "Bạn phải đảm bảo đã kiểm tra nội dung và có toàn quyền sử dụng hợp pháp video này."
            )
            warn_box.setStyleSheet(
                f"color: #fde68a; font-size: {tokens.FONT_SIZE_SM}px; padding: 10px; "
                f"background-color: {tokens.WARNING_BG}; border: 1px solid {tokens.WARNING_BORDER}; border-radius: {tokens.RADIUS_MD}px;"
            )
        warn_box.setWordWrap(True)
        layout.addWidget(warn_box)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(tokens.SPACE_SM)
        btn_layout.addStretch()

        self.btn_cancel = AppButton("Hủy bỏ", variant="secondary", parent=self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        confirm_btn_text = "Xác nhận chạy thử (Dry-run)" if dry_run else "Xác nhận và Tải lên"
        confirm_icon = "test" if dry_run else "upload"
        self.btn_confirm = AppButton(confirm_btn_text, variant="primary", icon_name=confirm_icon, parent=self)
        self.btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)

    def _add_row(self, layout: QVBoxLayout, label: str, value: str) -> None:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-weight: 600; min-width: 140px;")
        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet(f"color: {tokens.TEXT_PRIMARY};")
        row.addWidget(lbl)
        row.addWidget(val, stretch=1)
        layout.addLayout(row)
