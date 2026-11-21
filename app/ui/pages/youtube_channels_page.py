"""YouTube Channels management page: Multi-account, Channel Stats and Video List."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QThreadPool, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QMenu, QSizePolicy, QAbstractItemView,
)

from app.ui import i18n as _i18n
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

        self._load_avatar()

        # Channel info
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        info_col.setContentsMargins(0, 0, 0, 0)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.lbl_title = QLabel(self.account.title, self)
        if not self.account.title:
            _i18n.set_text(self.lbl_title, "Kênh YouTube")
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_title.setMinimumWidth(0)
        self.lbl_title.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {tokens.TEXT_PRIMARY}; border: none; background: transparent;")
        title_row.addWidget(self.lbl_title, stretch=1)

        if self.account.is_default:
            self.badge_def = StatusBadge(status="Mặc định", badge_type="info", parent=self)
            title_row.addWidget(self.badge_def)

        info_col.addLayout(title_row)

        self.lbl_id = QLabel(f"ID: {self.account.id}", self)
        self.lbl_id.setStyleSheet(f"font-size: 11px; color: {tokens.TEXT_MUTED}; border: none; background: transparent;")
        self.lbl_title.setToolTip(f"{self.account.title}\n{self.account.id}")
        self.lbl_id.hide()
        self.lbl_metrics = _i18n.ui(QLabel("— đăng ký  ·  — lượt xem  ·  — video", self))
        self.lbl_metrics.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;")
        self.lbl_metrics.setWordWrap(True)
        self.lbl_metrics.setMinimumWidth(0)
        info_col.addWidget(self.lbl_metrics)

        layout.addLayout(info_col, stretch=1)

        # Status badge
        badge_type = "success" if self.account.status == "connected" else "danger"
        badge_text = "Đã kết nối" if self.account.status == "connected" else (
            "Hết hạn" if self.account.status == "expired" else "Lỗi"
        )
        self.status_badge = _i18n.bind(QLabel(self), badge_text)
        status_color = "#34d399" if self.account.status == "connected" else "#f87171"
        self.status_badge.setStyleSheet(f"color: {status_color}; font-size: 12px; border: none; background: transparent;")
        layout.addWidget(self.status_badge)

        self.btn_menu = AppButton("...", variant="ghost", parent=self)
        self.btn_menu.setFixedSize(36, 36)
        self.btn_menu.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        _i18n.tooltip(self.btn_menu, "Thao tác tài khoản")
        _i18n.bind(self.btn_menu, "Thao tác tài khoản", "accessibleName")
        menu = QMenu(self.btn_menu)
        if not self.account.is_default:
            menu.addAction("Đặt làm mặc định", lambda: self.set_default_requested.emit(self.account))
        if self.account.status == "expired":
            menu.addAction("Đăng nhập lại", lambda: self.reconnect_requested.emit(self.account))
        menu.addSeparator()
        menu.addAction("Xóa tài khoản", lambda: self.remove_requested.emit(self.account))
        def translate_menu():
            for action in menu.actions():
                source = action.property('ui_source')
                if source is None:
                    source = action.text()
                    action.setProperty('ui_source', source)
                action.setText(_i18n.translate(source, _i18n.language_for(self)))
        menu.aboutToShow.connect(translate_menu)
        self.btn_menu.setMenu(menu)
        layout.addWidget(self.btn_menu)
        self.setFixedHeight(84)

    def _load_avatar(self) -> None:
        owner = self.parent()
        while owner is not None:
            services = getattr(owner, 'services', None)
            if services is not None and not services.run_automatic_background:
                return
            owner = owner.parent()
        url = QUrl(self.account.thumbnail_url or "")
        if url.scheme() != "https" or not url.host() or url.userInfo():
            return
        self._avatar_network = QNetworkAccessManager(self)
        request = QNetworkRequest(url)
        request.setTransferTimeout(10000)
        reply = self._avatar_network.get(request)
        reply.finished.connect(lambda: self._avatar_finished(reply))
        # Channel thumbnails are tiny; reject unexpectedly large responses.
        reply.downloadProgress.connect(lambda received, total: reply.abort() if received > 2_000_000 else None)

    def _avatar_finished(self, reply) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(reply.readAll())):
                self._set_avatar(pixmap)
        reply.deleteLater()

    def _set_avatar(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        size = self.lbl_avatar.size()
        scaled = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        rounded = QPixmap(size)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addEllipse(0, 0, size.width(), size.height())
        painter.setClipPath(clip)
        painter.drawPixmap((size.width() - scaled.width()) // 2,
                           (size.height() - scaled.height()) // 2, scaled)
        painter.end()
        self.lbl_avatar.setStyleSheet("background: transparent; border: none;")
        self.lbl_avatar.setPixmap(rounded)

    def set_stats(self, stats: ChannelStats) -> None:
        subscribers = _i18n.translate("Ẩn", _i18n.language_for(self)) if stats.subscribers_hidden else (
            f"{stats.subscribers:,}" if stats.subscribers is not None else "—")
        _i18n.format_text(self.lbl_metrics, '{0} đăng ký  ·  {1} lượt xem  ·  {2} video', subscribers, f'{stats.total_views:,}', f'{stats.video_count:,}')
        _i18n.tooltip(self.lbl_metrics, "Số người đăng ký có thể được YouTube làm tròn.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.lbl_title.setText(self.lbl_title.fontMetrics().elidedText(
            self.account.title or "Kênh YouTube", Qt.TextElideMode.ElideRight,
            self.lbl_title.width()))

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
        if self.services.run_automatic_background:
            self._load_accounts()

    def _bind_empty_copy(self, widget):
        for label in widget.findChildren(QLabel):
            if label.text():
                _i18n.bind(label, label.text())

    def _tr(self, text):
        return _i18n.translate(text, _i18n.language_for(self))

    def _notify(self, ntype: str, title: str, message: str) -> None:
        toast = ToastManager.instance()
        if toast:
            getattr(toast, ntype, toast.info)(self._tr(title), self._tr(message))

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # Header
        head_row = QHBoxLayout()
        head_info = QVBoxLayout()
        head_info.setSpacing(2)
        head_title = _i18n.ui(QLabel("Quản lý Kênh YouTube", self))
        head_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        head_info.addWidget(head_title)

        head_sub = _i18n.ui(QLabel("Theo dõi hiệu suất kênh, chuyển đổi tài khoản và quản lý danh sách video đã tải lên.", self))
        head_sub.setWordWrap(True)
        head_sub.setProperty("class", "hintLabel")
        head_info.addWidget(head_sub)
        head_row.addLayout(head_info, stretch=1)

        self.btn_add_account = _i18n.ui(AppButton("Thêm tài khoản", variant="primary", icon_name="user-add", parent=self))
        self.btn_add_account.clicked.connect(self._on_add_account)
        head_row.addWidget(self.btn_add_account, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(head_row)

        # Progress bar for background ops
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Account List Card
        self.card_accounts = Card(title="Tài khoản đã kết nối", parent=self)
        acc_layout = QVBoxLayout()
        acc_layout.setSpacing(8)

        self.accounts_container = QVBoxLayout()
        self.accounts_container.setSpacing(8)
        acc_layout.addLayout(self.accounts_container)

        self.card_accounts.add_layout(acc_layout)
        self.card_accounts.setObjectName("channelAccounts")
        self.card_accounts.setStyleSheet("QFrame#channelAccounts { padding: 0px; }")
        self.card_accounts.main_layout.setContentsMargins(18, 14, 18, 14)
        self.card_accounts.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_accounts.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.card_accounts)

        # Videos Table Card
        self.card_videos = Card(parent=self)
        v_layout = QVBoxLayout()
        v_layout.setSpacing(10)

        self.lbl_video_heading = _i18n.ui(QLabel("Video của kênh", self.card_videos))
        self.lbl_video_heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        v_layout.addWidget(self.lbl_video_heading)
        self.details_placeholder = _i18n.ui(QLabel("Chọn kênh để xem danh sách video", self.card_videos))
        self.details_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_placeholder.setMinimumHeight(160)
        self.details_placeholder.setProperty("class", "hintLabel")
        v_layout.addWidget(self.details_placeholder, stretch=1)

        # Filter and toolbar row
        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)

        self.edit_search = QLineEdit(self.card_videos)
        _i18n.placeholder(self.edit_search, "Tìm kiếm video theo tiêu đề hoặc ID...")
        self.edit_search.textChanged.connect(self._filter_videos)
        tool_row.addWidget(self.edit_search, stretch=1)

        self.lbl_updated_at = _i18n.ui(QLabel("Chưa cập nhật", self.card_videos))
        self.lbl_updated_at.setProperty("class", "hintLabel")
        self.lbl_updated_at.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tool_row.addWidget(self.lbl_updated_at)

        v_layout.addLayout(tool_row)

        # Video Table
        self.tbl_videos = QTableWidget(self.card_videos)
        self.tbl_videos.setColumnCount(7)
        _i18n.headers(self.tbl_videos, [
            "Mã Video", "Tiêu đề", "Ngày đăng", "Chế độ", "Lượt xem", "Lượt thích", "Bình luận"
        ])
        v_head = self.tbl_videos.horizontalHeader()
        v_head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        v_head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_head.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tbl_videos.setColumnWidth(2, 160)
        v_head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        v_head.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        v_head.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        v_head.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_videos.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_videos.setSortingEnabled(True)
        self.tbl_videos.setAlternatingRowColors(False)
        self.tbl_videos.setMinimumHeight(150)
        self.tbl_videos.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tbl_videos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_videos.verticalHeader().hide()
        self.tbl_videos.setShowGrid(False)
        self.tbl_videos.verticalHeader().setDefaultSectionSize(40)
        self.tbl_videos.doubleClicked.connect(self._on_table_double_clicked)
        v_layout.addWidget(self.tbl_videos, stretch=1)

        self.empty_videos = EmptyState(
            icon_name="video",
            title="Kênh chưa có video nào",
            description="Kênh YouTube này chưa có video đã đăng tải hoặc đang tải danh sách.",
            parent=self.card_videos,
        )
        self._bind_empty_copy(self.empty_videos)
        self.empty_videos.setVisible(False)
        v_layout.addWidget(self.empty_videos, stretch=1)

        self.tbl_videos.hide()
        self.edit_search.hide()
        self.lbl_updated_at.hide()
        self.card_videos.setObjectName("channelVideos")
        self.card_videos.setStyleSheet("QFrame#channelVideos { padding: 0px; }")
        self.card_videos.main_layout.setContentsMargins(18, 14, 18, 14)
        self.card_videos.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.card_videos.add_layout(v_layout)
        layout.addWidget(self.card_videos, stretch=1)

        # Compatibility attributes for upload results
        self.lbl_result_link = QLabel(self)
        self.lbl_result_link.setVisible(False)
        self.btn_open_youtube = QPushButton(self)
        self.btn_open_youtube.setVisible(False)
        self.btn_copy_link = QPushButton(self)
        self.btn_copy_link.setVisible(False)
        self.btn_open = self.btn_open_youtube
        self.btn_copy = self.btn_copy_link

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
        while self.accounts_container.count():
            item = self.accounts_container.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._card_widgets.clear()

        try:
            acc_list = list(accounts) if accounts else []
        except (TypeError, ValueError):
            acc_list = []

        if not acc_list:
            self.card_accounts.setFixedHeight(180)
            empty = EmptyState(
                icon_name="youtube",
                title="Chưa có tài khoản, hãy thêm tài khoản YouTube",
                description="Hãy kết nối tài khoản để bắt đầu quản lý và đăng tải video.",
                parent=self.card_accounts,
            )
            self._bind_empty_copy(empty)
            self.accounts_container.addWidget(empty)
            self._card_widgets.append(empty)
            self._selected_account = None
            self._show_channel_details(None)
            return

        self.card_accounts.setFixedHeight(70 + len(acc_list) * 84 + max(0, len(acc_list) - 1) * 8)
        # Preserve an explicit selection after account changes; initial view stays unselected.
        selected_id = self._selected_account.id if self._selected_account else None
        self._selected_account = next((a for a in acc_list if a.id == selected_id), None)

        for acc in acc_list:
            card = AccountCardWidget(acc, is_selected=(self._selected_account is not None and acc.id == self._selected_account.id), parent=self.card_accounts)
            card.selected.connect(self._select_account)
            card.set_default_requested.connect(self._on_set_default_for_account)
            card.reconnect_requested.connect(self._on_reconnect_for_account)
            card.remove_requested.connect(self._on_remove_account_for_account)
            self.accounts_container.addWidget(card)
            self._card_widgets.append(card)
            if self.services.run_automatic_background:
                worker = FetchChannelStatsWorker(self.services.youtube, acc.id)
                worker.signals.finished.connect(self._on_stats_loaded)
                worker.signals.error.connect(lambda _error, channel_id=acc.id: self._on_row_stats_error(channel_id))
                self.thread_pool.start(worker)

        self._show_channel_details(self._selected_account)
        self._update_action_bar_state()
        self._load_channel_data(force_refresh=False)

    def _select_account(self, account: ChannelAccount) -> None:
        self._selected_account = account
        self._show_channel_details(account)
        for c in self._card_widgets:
            if hasattr(c, "account"):
                c.update_selection(c.account.id == account.id)
        self._update_action_bar_state()
        self._load_channel_data(force_refresh=False)

    def _update_action_bar_state(self) -> None:
        # Actions belong to each channel menu, never to a duplicate toolbar.
        pass

    def _show_channel_details(self, account: ChannelAccount | None) -> None:
        self._all_videos = []
        self.empty_videos.hide()
        self.tbl_videos.setRowCount(0)
        self.edit_search.clear()
        self.details_placeholder.setVisible(account is None)
        self.tbl_videos.setVisible(account is not None)
        self.edit_search.setVisible(account is not None)
        self.lbl_updated_at.setVisible(account is not None)
        _i18n.set_text(self.lbl_updated_at, "Đang tải video…" if account else "")
        if account:
            _i18n.format_text(self.lbl_video_heading, 'Video · {0}', account.title)
        else:
            _i18n.set_text(self.lbl_video_heading, 'Video của kênh')
        self.lbl_video_heading.setTextFormat(Qt.TextFormat.PlainText)

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

    def _on_row_stats_error(self, channel_id: str) -> None:
        for card in self._card_widgets:
            if hasattr(card, "account") and card.account.id == channel_id:
                _i18n.set_text(card.lbl_metrics, "Chưa tải được thống kê")
                _i18n.tooltip(card.lbl_metrics, "Kiểm tra kết nối hoặc đăng nhập lại tài khoản.")
                break

    @Slot(object)
    def _on_stats_loaded(self, stats: ChannelStats) -> None:
        for card in self._card_widgets:
            if hasattr(card, "account") and card.account.id == stats.channel_id:
                card.set_stats(stats)
                break

    @Slot(object)
    def _on_videos_loaded(self, videos: list[VideoStats]) -> None:
        self.progress_bar.setVisible(False)
        self._all_videos = videos
        fetched = min((v.fetched_at for v in videos if v.fetched_at is not None), default=None)
        stamp = fetched.astimezone().strftime("%H:%M:%S %d/%m/%Y") if fetched else self._tr('chưa có thời điểm cập nhật')
        _i18n.format_text(self.lbl_updated_at, 'Cập nhật: {0}', stamp)
        self._render_videos(videos)

    @Slot(str, object)
    def _on_channel_videos_loaded(self, channel_id, videos):
        if self._selected_account is not None and self._selected_account.id == channel_id:
            self._on_videos_loaded(videos)

    def _render_videos(self, videos: list[VideoStats]) -> None:
        if not videos:
            self.tbl_videos.setVisible(False)
            self.empty_videos.setVisible(True)
            self.tbl_videos.setRowCount(0)
            return

        self.empty_videos.setVisible(False)
        self.tbl_videos.setVisible(True)
        self.tbl_videos.setSortingEnabled(False)
        self.tbl_videos.setRowCount(len(videos))

        for row, v in enumerate(videos):
            self.tbl_videos.setItem(row, 0, QTableWidgetItem(v.video_id))
            self.tbl_videos.setItem(row, 1, QTableWidgetItem(v.title))

            date_str = v.published_at.strftime("%d/%m/%Y %H:%M") if v.published_at else "—"
            self.tbl_videos.setItem(row, 2, QTableWidgetItem(date_str))

            privacy_map = {"public": "Công khai", "private": "Riêng tư", "unlisted": "Không công khai"}
            self.tbl_videos.setItem(row, 3, QTableWidgetItem(self._tr(privacy_map.get(v.privacy_status, v.privacy_status))))

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
        self._notify("success", "Thêm tài khoản thành công", self._tr("Đã kết nối tài khoản: {0}").format(account.title))
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
            title=self._tr("Xác nhận xóa tài khoản"),
            message=self._tr("Bạn có chắc chắn muốn ngắt kết nối và xóa tài khoản '{0}' không?").format(account.title),
            confirm_text=self._tr("Xóa tài khoản"),
            cancel_text=self._tr("Hủy"),
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
