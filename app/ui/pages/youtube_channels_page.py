"""YouTube Channels management page: Multi-account, Channel Stats and Video List."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.contracts import ChannelAccount, ChannelStats, VideoStats
from app.ui import tokens
from app.ui.components import (
    AppButton, Card, ConfirmDialog, EmptyState, StatCard, StatusBadge,
    ToastManager,
)
from app.ui.icons import get_icon
from app.ui.services import ServiceContainer
from app.ui.state import JobState
from app.workers import (
    AddAccountWorker, FetchAccountsWorker, FetchChannelStatsWorker,
    FetchChannelVideosWorker, RemoveAccountWorker, SetDefaultAccountWorker,
)


class AccountCardWidget(QFrame):
    """Clickable card displaying account thumbnail/avatar, title, status and per-account actions."""

    set_default_requested = Signal(object)
    reconnect_requested = Signal(object)
    remove_requested = Signal(object)
    selected = Signal(object)

    def __init__(
        self,
        account: ChannelAccount,
        is_selected: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.account = account
        self.is_selected = is_selected
        self.setObjectName("accountCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._init_ui()
        self.update_selection(is_selected)

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Avatar initial
        self.lbl_avatar = QLabel(self)
        self.lbl_avatar.setFixedSize(40, 40)
        self.lbl_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        initial = (self.account.title[:1] or "Y").upper()
        self.lbl_avatar.setText(initial)
        # Background color hash based on title
        color_val = abs(hash(self.account.title or "yt")) % 5
        palette = ["#3b82f6", "#ef4444", "#10b981", "#8b5cf6", "#f59e0b"]
        bg_col = palette[color_val]
        self.lbl_avatar.setStyleSheet(
            f"background-color: {bg_col}; color: #ffffff; border-radius: 20px; "
            f"font-weight: 700; font-size: 16px; border: none;"
        )
        layout.addWidget(self.lbl_avatar)

        # Channel info
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        info_col.setContentsMargins(0, 0, 0, 0)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.lbl_title = QLabel(self.account.title or "Kênh YouTube", self)
        self.lbl_title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {tokens.TEXT_PRIMARY}; border: none; background: transparent;")
        title_row.addWidget(self.lbl_title)

        if self.account.is_default:
            self.badge_def = StatusBadge(status="Mặc định", badge_type="info", parent=self)
            title_row.addWidget(self.badge_def)
        title_row.addStretch()
        info_col.addLayout(title_row)

        self.lbl_id = QLabel(f"ID: {self.account.id}", self)
        self.lbl_id.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED}; border: none; background: transparent;")
        info_col.addWidget(self.lbl_id)

        layout.addLayout(info_col, stretch=1)

        # Status badge
        badge_type = "success" if self.account.status == "connected" else "danger"
        badge_text = "Đã kết nối" if self.account.status == "connected" else (
            "Hết hạn" if self.account.status == "expired" else "Lỗi"
        )
        self.status_badge = StatusBadge(status=badge_text, badge_type=badge_type, parent=self)
        layout.addWidget(self.status_badge)

        # Integrated per-account action buttons
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        # "Đăng nhập lại" only visible when expired
        self.btn_card_reconnect = AppButton("Đăng nhập lại", variant="ghost", icon_name="refresh", parent=self)
        self.btn_card_reconnect.setVisible(self.account.status == "expired")
        self.btn_card_reconnect.clicked.connect(lambda: self.reconnect_requested.emit(self.account))
        actions_row.addWidget(self.btn_card_reconnect)

        # "Đặt làm mặc định" hidden when account is already default
        self.btn_card_set_default = AppButton("Đặt làm mặc định", variant="secondary", icon_name="check", parent=self)
        self.btn_card_set_default.setVisible(not self.account.is_default)
        self.btn_card_set_default.clicked.connect(lambda: self.set_default_requested.emit(self.account))
        actions_row.addWidget(self.btn_card_set_default)

        # "Xóa tài khoản"
        self.btn_card_remove = AppButton("Xóa", variant="danger", icon_name="delete", parent=self)
        self.btn_card_remove.clicked.connect(lambda: self.remove_requested.emit(self.account))
        actions_row.addWidget(self.btn_card_remove)

        layout.addLayout(actions_row)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.selected.emit(self.account)

    def update_selection(self, selected: bool) -> None:
        self.is_selected = selected
        border_col = tokens.COLOR_PRIMARY if selected else tokens.BORDER_SUBTLE
        bg_col = tokens.BG_CARD_HOVER if selected else tokens.BG_CARD
        self.setStyleSheet(
            f"QFrame#accountCard {{ background-color: {bg_col}; border: 1.5px solid {border_col}; "
            f"border-radius: {tokens.RADIUS_MD}px; }}"
            f"QFrame#accountCard:hover {{ border-color: {tokens.COLOR_PRIMARY_HOVER}; }}"
            f"QFrame#accountCard QLabel {{ border: none; background: transparent; }}"
        )


class YouTubeChannelsPage(QWidget):
    """YouTube multi-account and channel management page."""

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

        self._accounts: list[ChannelAccount] = []
        self._selected_account: Optional[ChannelAccount] = None
        self._all_videos: list[VideoStats] = []
        self._card_widgets: list[AccountCardWidget] = []

        self._init_ui()
        self.services.add_mode_banner(self)
        self._load_accounts()

    def _notify(self, ntype: str, title: str, message: str) -> None:
        toast = ToastManager.instance()
        if toast:
            getattr(toast, ntype, toast.info)(title, message)

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)

        # Header
        head_row = QHBoxLayout()
        head_info = QVBoxLayout()
        head_title = QLabel("Quản lý Kênh YouTube", container)
        head_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        head_info.addWidget(head_title)

        head_sub = QLabel("Theo dõi hiệu suất kênh, chuyển đổi tài khoản và quản lý danh sách video đã tải lên.", container)
        head_sub.setProperty("class", "hintLabel")
        head_info.addWidget(head_sub)
        head_row.addLayout(head_info, stretch=1)

        self.btn_add_account = AppButton("Thêm tài khoản", variant="primary", icon_name="user-add", parent=container)
        self.btn_add_account.clicked.connect(self._on_add_account)
        head_row.addWidget(self.btn_add_account)

        self.btn_refresh_all = AppButton("Làm mới", variant="ghost", icon_name="refresh", parent=container)
        self.btn_refresh_all.clicked.connect(self._on_refresh_all)
        head_row.addWidget(self.btn_refresh_all)
        layout.addLayout(head_row)

        # Progress bar for background ops
        self.progress_bar = QProgressBar(container)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Account List Card
        self.card_accounts = Card(title="Danh sách tài khoản YouTube kết nối", parent=container)
        acc_layout = QVBoxLayout()
        acc_layout.setSpacing(10)

        self.accounts_container = QVBoxLayout()
        self.accounts_container.setSpacing(8)
        acc_layout.addLayout(self.accounts_container)

        # Action bar for selected account with clear target indicator
        self.acc_actions_widget = QWidget(self.card_accounts)
        self.acc_actions_bar = QHBoxLayout(self.acc_actions_widget)
        self.acc_actions_bar.setContentsMargins(0, 4, 0, 0)
        self.acc_actions_bar.setSpacing(8)

        self.lbl_selected_acc_target = QLabel("", self.acc_actions_widget)
        self.lbl_selected_acc_target.setStyleSheet(f"font-size: 12px; color: {tokens.TEXT_SECONDARY}; border: none; background: transparent;")
        self.acc_actions_bar.addWidget(self.lbl_selected_acc_target)
        self.acc_actions_bar.addStretch()

        self.btn_set_default = AppButton("Đặt làm mặc định", variant="secondary", icon_name="check", parent=self.card_accounts)
        self.btn_set_default.clicked.connect(self._on_set_default)
        self.acc_actions_bar.addWidget(self.btn_set_default)

        self.btn_reconnect = AppButton("Đăng nhập lại", variant="ghost", icon_name="refresh", parent=self.card_accounts)
        self.btn_reconnect.clicked.connect(self._on_reconnect)
        self.acc_actions_bar.addWidget(self.btn_reconnect)

        self.btn_remove_account = AppButton("Xóa tài khoản", variant="danger", icon_name="delete", parent=self.card_accounts)
        self.btn_remove_account.clicked.connect(self._on_remove_account)
        self.acc_actions_bar.addWidget(self.btn_remove_account)

        acc_layout.addWidget(self.acc_actions_widget)

        self.card_accounts.add_layout(acc_layout)
        layout.addWidget(self.card_accounts)

        # Stats Cards Row
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)

        self.stat_subscribers = StatCard(
            title="Người đăng ký",
            value="—",
            change_text="Số người đăng ký có thể bị làm tròn bởi YouTube",
            icon_name="author",
            parent=container,
        )
        self.stats_row.addWidget(self.stat_subscribers)

        self.stat_views = StatCard(
            title="Tổng lượt xem",
            value="—",
            change_text="Lượt xem toàn bộ kênh",
            icon_name="eye",
            parent=container,
        )
        self.stats_row.addWidget(self.stat_views)

        self.stat_videos = StatCard(
            title="Số lượng video",
            value="—",
            change_text="Tổng video đã đăng tải",
            icon_name="video",
            parent=container,
        )
        self.stats_row.addWidget(self.stat_videos)
        layout.addLayout(self.stats_row)

        # Videos Table Card
        self.card_videos = Card(title="Danh sách video của kênh", parent=container)
        v_layout = QVBoxLayout()
        v_layout.setSpacing(12)

        # Filter and toolbar row
        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)

        self.edit_search = QLineEdit(self.card_videos)
        self.edit_search.setPlaceholderText("Tìm kiếm video theo tiêu đề hoặc ID...")
        self.edit_search.textChanged.connect(self._filter_videos)
        tool_row.addWidget(self.edit_search, stretch=1)

        self.lbl_updated_at = QLabel("Chưa cập nhật", self.card_videos)
        self.lbl_updated_at.setProperty("class", "hintLabel")
        tool_row.addWidget(self.lbl_updated_at)

        self.btn_refresh_videos = AppButton("Làm mới", variant="secondary", icon_name="refresh", parent=self.card_videos)
        self.btn_refresh_videos.clicked.connect(lambda: self._load_channel_data(force_refresh=True))
        tool_row.addWidget(self.btn_refresh_videos)
        v_layout.addLayout(tool_row)

        # Video Table
        self.tbl_videos = QTableWidget(self.card_videos)
        self.tbl_videos.setColumnCount(7)
        self.tbl_videos.setHorizontalHeaderLabels([
            "Mã Video", "Tiêu đề", "Ngày đăng", "Chế độ", "Lượt xem", "Lượt thích", "Bình luận"
        ])
        self.tbl_videos.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_videos.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_videos.setSortingEnabled(True)
        self.tbl_videos.setAlternatingRowColors(True)
        self.tbl_videos.setMinimumHeight(320)
        self.tbl_videos.doubleClicked.connect(self._on_table_double_clicked)
        v_layout.addWidget(self.tbl_videos)

        # Bottom row of table
        act_row = QHBoxLayout()
        self.btn_open_yt = AppButton("Mở video trên YouTube", variant="ghost", icon_name="link", parent=self.card_videos)
        self.btn_open_yt.clicked.connect(self._on_open_selected_video_youtube)
        act_row.addWidget(self.btn_open_yt)
        act_row.addStretch()
        v_layout.addLayout(act_row)

        self.card_videos.add_layout(v_layout)
        layout.addWidget(self.card_videos)

        # Compatibility attributes for upload results
        self.lbl_result_link = QLabel(self)
        self.lbl_result_link.setVisible(False)
        self.btn_open_youtube = QPushButton(self)
        self.btn_open_youtube.setVisible(False)
        self.btn_copy_link = QPushButton(self)
        self.btn_copy_link.setVisible(False)
        self.btn_open = self.btn_open_youtube
        self.btn_copy = self.btn_copy_link

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    # =========================================================================
    # LOGIC & WORKERS
    # =========================================================================
    def _load_accounts(self) -> None:
        self.progress_bar.setVisible(True)
        worker = FetchAccountsWorker(self.services.youtube)
        worker.signals.finished.connect(self._on_accounts_loaded)
        worker.signals.error.connect(self._on_op_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_accounts_loaded(self, accounts: list[ChannelAccount]) -> None:
        self.progress_bar.setVisible(False)
        self._accounts = accounts
        self.services.connection.set_accounts(accounts)

        # Clear existing card widgets
        for c in self._card_widgets:
            c.deleteLater()
        self._card_widgets.clear()

        try:
            acc_list = list(accounts) if accounts else []
        except (TypeError, ValueError):
            acc_list = []

        if not acc_list:
            if hasattr(self, "acc_actions_widget"):
                self.acc_actions_widget.setVisible(False)
            empty = EmptyState(
                icon_name="youtube",
                title="Chưa có tài khoản, hãy thêm tài khoản YouTube",
                description="Hãy kết nối tài khoản để bắt đầu quản lý và đăng tải video.",
                parent=self.card_accounts,
            )
            self.accounts_container.addWidget(empty)
            self._card_widgets.append(empty)
            self._selected_account = None
            self.stat_subscribers.set_value("—")
            self.stat_views.set_value("—")
            self.stat_videos.set_value("—")
            self.tbl_videos.setRowCount(0)
            return

        # Render account cards
        default_acc = next((a for a in acc_list if getattr(a, "is_default", False)), acc_list[0])
        self._selected_account = default_acc

        for acc in acc_list:
            card = AccountCardWidget(acc, is_selected=(acc.id == default_acc.id), parent=self.card_accounts)
            card.selected.connect(self._select_account)
            card.set_default_requested.connect(self._on_set_default_for_account)
            card.reconnect_requested.connect(self._on_reconnect_for_account)
            card.remove_requested.connect(self._on_remove_account_for_account)
            self.accounts_container.addWidget(card)
            self._card_widgets.append(card)

        self._update_action_bar_state()
        self._load_channel_data(force_refresh=False)

    def _select_account(self, account: ChannelAccount) -> None:
        self._selected_account = account
        for c in self._card_widgets:
            if hasattr(c, "account"):
                c.update_selection(c.account.id == account.id)
        self._update_action_bar_state()
        self._load_channel_data(force_refresh=False)

    def _update_action_bar_state(self) -> None:
        if not hasattr(self, "acc_actions_widget"):
            return
        if not self._selected_account:
            self.acc_actions_widget.setVisible(False)
            return
        self.acc_actions_widget.setVisible(True)
        self.lbl_selected_acc_target.setText(f"Thao tác cho tài khoản đang chọn: <b>{self._selected_account.title}</b>")
        self.btn_set_default.setVisible(not self._selected_account.is_default)
        self.btn_reconnect.setVisible(self._selected_account.status == "expired")
        self.btn_remove_account.setVisible(True)

    def _load_channel_data(self, force_refresh: bool = False) -> None:
        if not self._selected_account:
            return

        ch_id = self._selected_account.id
        self.progress_bar.setVisible(True)

        # Worker for Channel Stats
        w_stats = FetchChannelStatsWorker(self.services.youtube, ch_id, force_refresh=force_refresh)
        w_stats.signals.finished.connect(self._on_stats_loaded)
        w_stats.signals.error.connect(self._on_op_error)
        self.thread_pool.start(w_stats)

        # Worker for Channel Videos
        w_vids = FetchChannelVideosWorker(self.services.youtube, ch_id, limit=50, force_refresh=force_refresh)
        w_vids.signals.channel_result.connect(self._on_channel_videos_loaded)
        w_vids.signals.error.connect(self._on_op_error)
        self.thread_pool.start(w_vids)

    @Slot(object)
    def _on_stats_loaded(self, stats: ChannelStats) -> None:
        if self._selected_account is not None and stats.channel_id != self._selected_account.id:
            return
        self.progress_bar.setVisible(False)
        if stats.subscribers_hidden:
            self.stat_subscribers.set_value("Ẩn")
        elif stats.subscribers is not None:
            self.stat_subscribers.set_value(f"{stats.subscribers:,}")
        else:
            self.stat_subscribers.set_value("—")

        self.stat_views.set_value(f"{stats.total_views:,}")
        self.stat_videos.set_value(f"{stats.video_count:,}")

    @Slot(object)
    def _on_videos_loaded(self, videos: list[VideoStats]) -> None:
        self.progress_bar.setVisible(False)
        self._all_videos = videos
        fetched = min((v.fetched_at for v in videos if v.fetched_at is not None), default=None)
        stamp = fetched.astimezone().strftime("%H:%M:%S %d/%m/%Y") if fetched else 'chưa có thời điểm cập nhật'
        self.lbl_updated_at.setText(f"Dữ liệu lưu lúc: {stamp}")
        self._render_videos(videos)

    @Slot(str, object)
    def _on_channel_videos_loaded(self, channel_id, videos):
        if self._selected_account is not None and self._selected_account.id == channel_id:
            self._on_videos_loaded(videos)

    def _render_videos(self, videos: list[VideoStats]) -> None:
        self.tbl_videos.setSortingEnabled(False)
        self.tbl_videos.setRowCount(len(videos))

        for row, v in enumerate(videos):
            self.tbl_videos.setItem(row, 0, QTableWidgetItem(v.video_id))
            self.tbl_videos.setItem(row, 1, QTableWidgetItem(v.title))

            date_str = v.published_at.strftime("%d/%m/%Y %H:%M") if v.published_at else "—"
            self.tbl_videos.setItem(row, 2, QTableWidgetItem(date_str))

            privacy_map = {"public": "Công khai", "private": "Riêng tư", "unlisted": "Không công khai"}
            self.tbl_videos.setItem(row, 3, QTableWidgetItem(privacy_map.get(v.privacy_status, v.privacy_status)))

            self.tbl_videos.setItem(row, 4, QTableWidgetItem(f"{v.views:,}"))
            likes_str = f"{v.likes:,}" if v.likes is not None else "—"
            self.tbl_videos.setItem(row, 5, QTableWidgetItem(likes_str))
            comm_str = f"{v.comments:,}" if v.comments is not None else "—"
            self.tbl_videos.setItem(row, 6, QTableWidgetItem(comm_str))

        self.tbl_videos.setSortingEnabled(True)

    @Slot(str)
    def _filter_videos(self, query: str) -> None:
        q = query.strip().lower()
        if not q:
            self._render_videos(self._all_videos)
            return

        filtered = [
            v for v in self._all_videos
            if q in v.title.lower() or q in v.video_id.lower()
        ]
        self._render_videos(filtered)

    @Slot()
    def _on_add_account(self) -> None:
        self.progress_bar.setVisible(True)
        worker = AddAccountWorker(self.services.youtube)
        worker.signals.finished.connect(self._on_account_added)
        worker.signals.error.connect(self._on_op_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def _on_account_added(self, account: ChannelAccount) -> None:
        self.progress_bar.setVisible(False)
        self._notify("success", "Thêm tài khoản thành công", f"Đã kết nối tài khoản: {account.title}")
        self._load_accounts()

    @Slot()
    def _on_set_default(self) -> None:
        if self._selected_account:
            self._on_set_default_for_account(self._selected_account)

    def _on_set_default_for_account(self, account: ChannelAccount) -> None:
        self.progress_bar.setVisible(True)
        worker = SetDefaultAccountWorker(self.services.youtube, account.id)
        worker.signals.finished.connect(self._default_changed)
        worker.signals.error.connect(self._on_op_error)
        self.thread_pool.start(worker)

    @Slot()
    def _on_reconnect(self) -> None:
        if self._selected_account:
            self._on_reconnect_for_account(self._selected_account)

    @Slot(object)
    def _default_changed(self, channel_id):
        self.services.connection.select_channel(channel_id)
        self._load_accounts()

    def _on_reconnect_for_account(self, account: ChannelAccount) -> None:
        self.progress_bar.setVisible(True)
        worker = AddAccountWorker(self.services.youtube)
        worker.signals.finished.connect(lambda acc: self._load_accounts())
        worker.signals.error.connect(self._on_op_error)
        self.thread_pool.start(worker)

    @Slot()
    def _on_remove_account(self) -> None:
        if self._selected_account:
            self._on_remove_account_for_account(self._selected_account)

    def _on_remove_account_for_account(self, account: ChannelAccount) -> None:
        dialog = ConfirmDialog(
            title="Xác nhận xóa tài khoản",
            message=f"Bạn có chắc chắn muốn ngắt kết nối và xóa tài khoản '{account.title}' không?",
            confirm_text="Xóa tài khoản",
            cancel_text="Hủy",
            is_danger=True,
            icon_name="delete",
            parent=self,
        )
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.progress_bar.setVisible(True)
            worker = RemoveAccountWorker(self.services.youtube, account.id)
            worker.signals.finished.connect(lambda ch_id: self._load_accounts())
            worker.signals.error.connect(self._on_op_error)
            self.thread_pool.start(worker)

    @Slot()
    def _on_refresh_all(self) -> None:
        self._load_accounts()

    @Slot(str)
    def _on_op_error(self, err: str) -> None:
        self.progress_bar.setVisible(False)
        self._notify("error", "Lỗi thao tác", err)

    @Slot()
    def _on_open_selected_video_youtube(self) -> None:
        row = self.tbl_videos.currentRow()
        if row < 0:
            self._notify("warning", "Chưa chọn video", "Vui lòng chọn một dòng video trong bảng.")
            return
        item_id = self.tbl_videos.item(row, 0)
        if item_id:
            vid_id = item_id.text().strip()
            url = f"https://www.youtube.com/watch?v={vid_id}"
            QDesktopServices.openUrl(QUrl(url))

    def _on_table_double_clicked(self) -> None:
        self._on_open_selected_video_youtube()
