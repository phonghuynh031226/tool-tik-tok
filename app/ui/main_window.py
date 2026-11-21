"""Main window of the application with responsive sidebar, page switching, and toast notifications."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtGui import QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from app.ui import i18n as _i18n
from app.contracts import JobStatus
from app.ui import branding, icons, tokens
from app.ui.components import ToastManager
from app.ui.pages import (
    DashboardPage, HistoryPage, HistorySchedulePage, SettingsPage,
    ToolsPage, YouTubeChannelsPage,
)
from app.ui.automation_controller import AutomationController
from app.ui.pages.automation_page import AutomationPage
from app.core.automation import AutomationStore
from app.ui.services import ServiceContainer, get_services
from app.ui.state import JobState
from app.ui.styles import apply_app_theme
from app.ui.appearance import UiPreferences


class MainWindow(QMainWindow):
    """Clivo main desktop application window."""

    def __init__(
        self,
        services: Optional[ServiceContainer] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(branding.APP_NAME)
        self.setWindowIcon(branding.get_app_icon())
        self.setMinimumSize(tokens.WINDOW_MIN_WIDTH, tokens.WINDOW_MIN_HEIGHT)
        self.resize(tokens.WINDOW_DEFAULT_WIDTH, tokens.WINDOW_DEFAULT_HEIGHT)

        # Injected services and single shared state instance
        self.services = services or get_services()
        self.job_state = JobState(self)
        self._sidebar_collapsed = False
        self._nav_items: List[Tuple[QPushButton, str, str]] = []

        self._closing = False
        self._resources_closed = False
        self._close_when_automation_idle = False
        self._init_ui()
        self._init_system_tray()
        self._connect_signals()
        self._apply_theme()
        self.ui_preferences = UiPreferences(self, self.services.settings)
        self.page_settings.appearance_changed.connect(self.ui_preferences.apply)
        self.ui_preferences.apply()

        QTimer.singleShot(0, self._restore_youtube_session)

    @Slot()
    def _restore_youtube_session(self):
        if not self._closing and not self.services.is_fake and hasattr(self.services, "connection"):
            self.services.connection.restore_service(self.services.youtube)

    def _init_system_tray(self) -> None:
        """Initialize system tray for notifications when window is unfocused."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(branding.get_app_icon())
        self.tray_icon.setToolTip(branding.APP_NAME)
        self.tray_icon.setVisible(True)

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # Left Responsive Sidebar
        # -------------------------------------------------------------
        self.sidebar = QFrame(central_widget)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(tokens.SIDEBAR_WIDTH_EXPANDED)
        self.sb_layout = QVBoxLayout(self.sidebar)
        self.sb_layout.setContentsMargins(
            tokens.SPACE_SM, tokens.SPACE_MD, tokens.SPACE_SM, tokens.SPACE_MD
        )
        self.sb_layout.setSpacing(tokens.SPACE_XS)

        # App Logo & Header
        self.header_frame = QFrame(self.sidebar)
        self.header_frame.setObjectName("sidebarHeader")
        self.hf_layout = QVBoxLayout(self.header_frame)
        self.hf_layout.setContentsMargins(tokens.SPACE_SM, 0, tokens.SPACE_SM, tokens.SPACE_MD)
        self.hf_layout.setSpacing(tokens.SPACE_XS)

        # Top brand row (Icon + Text)
        self.brand_row = QHBoxLayout()
        self.brand_row.setSpacing(tokens.SPACE_SM)
        self.lbl_logo_icon = QLabel(self.header_frame)
        self.lbl_logo_icon.setPixmap(branding.get_logo_pixmap(28))
        self.lbl_logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_row.addWidget(self.lbl_logo_icon)

        self.lbl_logo_title = QLabel(branding.APP_NAME, self.header_frame)
        self.lbl_logo_title.setObjectName("appLogoTitle")
        self.brand_row.addWidget(self.lbl_logo_title)
        self.brand_row.addStretch()
        self.hf_layout.addLayout(self.brand_row)

        self.lbl_sub = QLabel(branding.APP_TAGLINE, self.header_frame)
        self.lbl_sub.setObjectName("appSubtitle")
        self.hf_layout.addWidget(self.lbl_sub)
        self.sb_layout.addWidget(self.header_frame)

        # Navigation Buttons Group (Zero Emojis, pure vector icons)
        self.nav_group = QButtonGroup(self.sidebar)
        self.nav_group.setExclusive(True)

        nav_definitions = [
            ("nav_dashboard", "Tổng quan", 0),
            ("nav_tools", "Công cụ", 1),
            ("nav_youtube", "Kênh YouTube", 2),
            ("sparkle", "Tự động hóa", 5),
            ("nav_history", "Lịch sử && Lịch đăng", 3),
            ("nav_settings", "Cài đặt", 4),
        ]

        for icon_name, label_text, page_idx in nav_definitions:
            btn = self._create_nav_button(icon_name, label_text, page_idx)
            self.sb_layout.addWidget(btn)

        self.sb_layout.addStretch()

        # Sidebar Footer: App name, version, and official logo
        self.footer_frame = QFrame(self.sidebar)
        self.footer_frame.setObjectName("sidebarFooter")
        ft_layout = QVBoxLayout(self.footer_frame)
        ft_layout.setContentsMargins(tokens.SPACE_SM, tokens.SPACE_SM, tokens.SPACE_SM, tokens.SPACE_SM)
        ft_layout.setSpacing(tokens.SPACE_XS)

        self.footer_brand_row = QHBoxLayout()
        self.footer_brand_row.setSpacing(tokens.SPACE_SM)

        self.lbl_footer_logo = QLabel(self.footer_frame)
        self.lbl_footer_logo.setFixedSize(18, 18)
        self.lbl_footer_logo.setPixmap(branding.get_logo_pixmap(18))
        self.footer_brand_row.addWidget(self.lbl_footer_logo)

        self.lbl_footer_title = QLabel(branding.APP_NAME, self.footer_frame)
        self.lbl_footer_title.setStyleSheet(f"font-weight: 600; font-size: {tokens.FONT_SIZE_SM}px; color: {tokens.TEXT_PRIMARY};")
        self.footer_brand_row.addWidget(self.lbl_footer_title)
        self.footer_brand_row.addStretch()
        ft_layout.addLayout(self.footer_brand_row)

        self.lbl_footer_version = _i18n.formatted(QLabel('', self.footer_frame), 'Phiên bản v{0}', f'{branding.APP_VERSION}')
        self.lbl_footer_version.setStyleSheet(f"font-size: {tokens.FONT_SIZE_XS}px; color: {tokens.TEXT_MUTED};")
        ft_layout.addWidget(self.lbl_footer_version)

        self.sb_layout.addWidget(self.footer_frame)
        root_layout.addWidget(self.sidebar)

        # -------------------------------------------------------------
        # Main Content Area (QStackedWidget)
        # -------------------------------------------------------------
        content_frame = QWidget(central_widget)
        cf_layout = QVBoxLayout(content_frame)
        cf_layout.setContentsMargins(0, 0, 0, 0)
        cf_layout.setSpacing(0)

        self.stack = QStackedWidget(content_frame)

        # Instantiate main pages with SHARED JobState and ServiceContainer
        self.page_dashboard = DashboardPage(self.job_state, self.services, self.stack)
        self.page_tools = ToolsPage(self.job_state, self.services, self.stack)
        self.page_youtube_channels = YouTubeChannelsPage(self.job_state, self.services, self.stack)
        self.page_history = HistoryPage(self.job_state, self.services, self.stack)
        self.page_settings = SettingsPage(self.job_state, self.services, self.stack)
        store = getattr(self.services, 'automation_store', None)
        self._owns_automation_store = store is None
        if store is None:
            development = type(self.services.settings).__module__ == 'app.services.fakes'
            store = AutomationStore(':memory:' if development else None)
        self.automation = AutomationController(self.services, self.page_dashboard, store, self)
        self.page_automation = AutomationPage(self.services, self.automation, self.stack)
        self.automation_bar = QWidget(self.page_dashboard)
        banner = QHBoxLayout(self.automation_bar)
        banner.setContentsMargins(20, 6, 20, 6)
        self.automation_status = QLabel(self.automation_bar)
        self.automation_status.setWordWrap(True)
        self.automation_status.setTextFormat(Qt.TextFormat.PlainText)
        banner.addWidget(self.automation_status, 1)
        self.btn_stop_automation = _i18n.ui(QPushButton('Tắt tự động', self.automation_bar))
        self.btn_stop_automation.clicked.connect(self.automation.deactivate)
        banner.addWidget(self.btn_stop_automation)
        self.page_dashboard.layout().insertWidget(0, self.automation_bar)
        self.automation.changed.connect(self._automation_changed)
        self._automation_changed()

        self.stack.addWidget(self.page_dashboard)         # Index 0
        self.stack.addWidget(self.page_tools)             # Index 1
        self.stack.addWidget(self.page_youtube_channels)  # Index 2
        self.stack.addWidget(self.page_history)           # Index 3
        self.stack.addWidget(self.page_settings)          # Index 4
        self.stack.addWidget(self.page_automation)        # Index 5

        # Backward compatibility aliases
        self.page_tiktok = self.page_tools
        self.page_ai = self.page_tools
        self.page_youtube = self.page_youtube_channels

        cf_layout.addWidget(self.stack)
        root_layout.addWidget(content_frame, stretch=1)

        # Navigation button references
        self.btn_nav_dashboard = self.nav_group.button(0)
        self.btn_nav_tools = self.nav_group.button(1)
        self.btn_nav_tiktok = self.btn_nav_tools
        self.btn_nav_ai = self.btn_nav_tools
        self.btn_nav_youtube = self.nav_group.button(2)
        self.btn_nav_history = self.nav_group.button(3)
        self.btn_nav_settings = self.nav_group.button(4)
        self.btn_nav_automation = self.nav_group.button(5)
        if self.btn_nav_dashboard:
            self.btn_nav_dashboard.setChecked(True)
        self.stack.setCurrentIndex(0)

        # Status label kept for programmatic state tracking & test compatibility
        self.lbl_active_job_status = _i18n.ui(QLabel("Chưa có tác vụ nào", self))
        self.lbl_active_job_status.setVisible(False)

        # Initialize Toast Manager (floating bottom-right non-blocking alerts)
        self.toast_manager = ToastManager(self)

    def _automation_changed(self):
        active = self.automation.armed_prompt_id is not None or self.automation.busy
        self.automation_bar.setVisible(active)
        self.automation_status.setText(self.automation.message)
        if self._close_when_automation_idle and not self.automation.busy:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        self._closing = True
        if self._resources_closed:
            super().closeEvent(event)
            return
        if hasattr(self, 'automation') and self.automation.busy:
            self._close_when_automation_idle = True
            self.automation.deactivate()
            event.ignore()
            return
        if hasattr(self, "automation"):
            self.automation.deactivate()
        self.ui_preferences.shutdown()
        self.services.connection.cancel_pending()
        # Shared service signals can still arrive after the window is closed.
        self.services.connection.changed.disconnect(self.page_automation.refresh)
        self.automation.changed.disconnect(self.page_automation.refresh)
        # Cancel this window's retained tasks, never the shared thread pool.
        seen = set()
        for widget in [self] + self.findChildren(QWidget):
            for name, worker in list(vars(widget).items()):
                if name.endswith('_worker') and worker is not None and id(worker) not in seen:
                    seen.add(id(worker))
                    cancel = getattr(worker, 'cancel', None)
                    if callable(cancel):
                        cancel()
        for player in self.findChildren(QMediaPlayer):
            player.stop()
            player.setSource(QUrl())
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.tray_icon.hide()
        if self._owns_automation_store:
            self.automation.store.close()
        self._resources_closed = True
        super().closeEvent(event)

    def _create_nav_button(self, icon_name: str, label_text: str, page_index: int) -> QPushButton:
        btn = _i18n.bind(QPushButton(f"  {label_text}", self.sidebar), f"  {label_text}")
        btn.setProperty("class", "navBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(icons.get_icon(icon_name))
        btn.setIconSize(QSize(18, 18))
        self.nav_group.addButton(btn, page_index)
        btn.clicked.connect(lambda: self._on_nav_clicked(page_index))
        self._nav_items.append((btn, icon_name, label_text))
        return btn

    def _apply_theme(self) -> None:
        apply_app_theme(self)

    def _connect_signals(self) -> None:
        self.job_state.status_changed.connect(self._on_status_changed)
        self.job_state.video_ready.connect(self._on_video_ready)
        self.page_history.navigate_requested.connect(self._navigate_to_page)

    def _navigate_to_page(self, index: int) -> None:
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
        self._on_nav_clicked(index)

    @Slot(int)
    def _on_nav_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 3:
            self.page_history.refresh_history()
            self.page_history.refresh_scheduled()
        elif index == 5:
            self.page_automation.refresh()
        elif index == 2:
            self.page_youtube_channels._load_accounts()

    # =========================================================================
    # Responsive Sidebar Logic
    # =========================================================================
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        new_width = event.size().width()
        should_collapse = new_width < tokens.SIDEBAR_COLLAPSE_THRESHOLD

        if should_collapse != self._sidebar_collapsed:
            self._sidebar_collapsed = should_collapse
            self._update_sidebar_state(should_collapse)

        # Reposition any floating toasts when window resizes
        if hasattr(self, "toast_manager"):
            self.toast_manager.reposition()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "toast_manager"):
            self.toast_manager.reposition()

    def _update_sidebar_state(self, collapsed: bool) -> None:
        """Toggle sidebar between expanded and compact icon-only mode."""
        if collapsed:
            self.sidebar.setFixedWidth(tokens.SIDEBAR_WIDTH_COLLAPSED)
            self.lbl_logo_title.setVisible(False)
            self.lbl_sub.setVisible(False)
            self.footer_frame.setVisible(False)
            self.header_frame.setContentsMargins(0, 0, 0, tokens.SPACE_MD)

            for btn, icon_name, label_text in self._nav_items:
                _i18n.set_text(btn, "")
                _i18n.tooltip(btn, _i18n.translate(label_text, _i18n.language_for(self)).replace("&&", "&"))
                btn.setProperty("class", "navBtnCollapsed")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        else:
            self.sidebar.setFixedWidth(tokens.SIDEBAR_WIDTH_EXPANDED)
            self.lbl_logo_title.setVisible(True)
            self.lbl_sub.setVisible(True)
            self.footer_frame.setVisible(True)
            self.header_frame.setContentsMargins(tokens.SPACE_SM, 0, tokens.SPACE_SM, tokens.SPACE_MD)

            for btn, icon_name, label_text in self._nav_items:
                _i18n.set_text(btn, f"  {label_text}")
                btn.setToolTip("")
                btn.setProperty("class", "navBtn")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    # =========================================================================
    # Toast & System Tray Notifications
    # =========================================================================
    def notify(
        self,
        toast_type: str,  # 'success', 'info', 'warning', 'error'
        title: str,
        message: str = "",
        action_text: Optional[str] = None,
        action_callback = None,
        duration_ms: int = 4500,
    ) -> None:
        """Display an in-app non-blocking toast, and mirror to system tray if window is not focused."""
        self.toast_manager.show(
            toast_type=toast_type,
            title=title,
            message=message,
            action_text=action_text,
            action_callback=action_callback,
            duration_ms=duration_ms,
        )

        # If window is minimized or not active, fire system tray balloon notification
        if not self.isActiveWindow() and self.tray_icon.isSystemTrayAvailable():
            tray_msg_icon = {
                "success": QSystemTrayIcon.MessageIcon.Information,
                "info": QSystemTrayIcon.MessageIcon.Information,
                "warning": QSystemTrayIcon.MessageIcon.Warning,
                "error": QSystemTrayIcon.MessageIcon.Critical,
            }.get(toast_type, QSystemTrayIcon.MessageIcon.Information)
            tray_title = f"{branding.APP_NAME} - {title}" if title else branding.APP_NAME
            self.tray_icon.showMessage(tray_title, message, tray_msg_icon, duration_ms)

    # =========================================================================
    # State change toast triggers
    # =========================================================================
    @Slot(str)
    def _on_status_changed(self, status: str) -> None:
        if status == "DRY_RUN":
            _i18n.set_text(self.lbl_active_job_status, "Đã chạy thử (chưa đăng YouTube)")
            self.notify("info", "Chạy thử hoàn tất", "Đã xác thực và mô phỏng luồng đăng YouTube an toàn (không upload thật).")
            return
        elif status == JobStatus.UPLOADED.value:
            _i18n.set_text(self.lbl_active_job_status, "Đã tải lên YouTube")
            url = self.job_state.upload_result.url if self.job_state.upload_result else ""
            def open_url():
                if url:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl(url))
            self.notify(
                "success",
                "Đăng video thành công!",
                "YouTube đã nhận video. Chế độ công khai phụ thuộc trạng thái thực tế trên YouTube.",
                action_text="Mở YouTube" if url else None,
                action_callback=open_url if url else None,
            )
            return
        elif status == JobStatus.SCHEDULED.value:
            _i18n.set_text(self.lbl_active_job_status, 'Đã hẹn giờ (chưa xác nhận công khai)')
            return
        elif status:
            self.lbl_active_job_status.setText(status)

        if status == JobStatus.METADATA_OK.value:
            self.notify("info", "Bắt đầu tải video", "Liên kết TikTok hợp lệ. Đang tiến hành tải video về máy...")
        elif status == JobStatus.CONTENT_READY.value:
            self.notify("success", "Tạo nội dung AI hoàn tất", "Tiêu đề, mô tả và thẻ tìm kiếm đã được tối ưu chuẩn SEO.")
        elif status == JobStatus.FAILED.value:
            err_msg = self.job_state.error_message or "Đã xảy ra lỗi trong quá trình xử lý tác vụ."
            self.notify("error", "Tác vụ thất bại", err_msg)

    @Slot(str)
    def _on_video_ready(self, path: str) -> None:
        from pathlib import Path
        file_name = Path(path).name
        self.notify("success", "Tải video hoàn tất", f"Tệp video đã lưu: {file_name}")


def run_app() -> int:
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    apply_app_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    import sys
    sys.exit(run_app())
