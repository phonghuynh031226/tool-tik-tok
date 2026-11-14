"""Main window of the application with responsive sidebar and page switching."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from app.ui.pages import (
    AIPage, DashboardPage, HistoryPage, SettingsPage, TikTokPage, YouTubePage,
)
from app.ui.services import ServiceContainer, get_services
from app.ui.state import JobState
from app.ui.styles import DARK_THEME_QSS


class MainWindow(QMainWindow):
    """TikTok YouTube Studio main desktop application window."""

    def __init__(
        self,
        services: Optional[ServiceContainer] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TikTok YouTube Studio")
        self.setMinimumSize(1000, 650)
        self.resize(1280, 720)

        # Injected services and single shared state instance
        self.services = services or get_services()
        self.job_state = JobState(self)

        self._init_ui()
        self._apply_theme()
        self._connect_signals()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # Left Sidebar
        # -------------------------------------------------------------
        self.sidebar = QFrame(central_widget)
        self.sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(8, 16, 8, 16)
        sb_layout.setSpacing(6)

        # App Logo & Title
        header_frame = QFrame(self.sidebar)
        header_frame.setObjectName("sidebarHeader")
        hf_layout = QVBoxLayout(header_frame)
        hf_layout.setContentsMargins(10, 4, 10, 12)
        hf_layout.setSpacing(2)

        lbl_logo = QLabel("🎬 Studio Pro", header_frame)
        lbl_logo.setObjectName("appLogoTitle")
        hf_layout.addWidget(lbl_logo)

        lbl_sub = QLabel("TikTok → YouTube Pipeline", header_frame)
        lbl_sub.setObjectName("appSubtitle")
        hf_layout.addWidget(lbl_sub)
        sb_layout.addWidget(header_frame)

        # Navigation Buttons Group
        self.nav_group = QButtonGroup(self.sidebar)
        self.nav_group.setExclusive(True)

        self.btn_nav_dashboard = self._create_nav_button("📊  Tổng quan (Dashboard)", 0)
        self.btn_nav_tiktok = self._create_nav_button("📥  Tải TikTok", 1)
        self.btn_nav_ai = self._create_nav_button("✨  Tạo nội dung AI", 2)
        self.btn_nav_youtube = self._create_nav_button("🚀  Đăng YouTube", 3)
        self.btn_nav_history = self._create_nav_button("📜  Lịch sử", 4)
        self.btn_nav_settings = self._create_nav_button("⚙️  Cài đặt", 5)

        for btn in (
            self.btn_nav_dashboard,
            self.btn_nav_tiktok,
            self.btn_nav_ai,
            self.btn_nav_youtube,
            self.btn_nav_history,
            self.btn_nav_settings,
        ):
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Job quick status in sidebar footer
        status_box = QFrame(self.sidebar)
        status_box.setStyleSheet(
            "background-color: #12141e; border: 1px solid #232736; border-radius: 8px; padding: 10px;"
        )
        st_layout = QVBoxLayout(status_box)
        st_layout.setContentsMargins(6, 6, 6, 6)
        st_layout.setSpacing(4)

        lbl_st_title = QLabel("Tác vụ hiện tại:")
        lbl_st_title.setStyleSheet("font-size: 11px; color: #94a3b8;")
        st_layout.addWidget(lbl_st_title)

        self.lbl_active_job_status = QLabel("Trống (Chưa có video)")
        self.lbl_active_job_status.setStyleSheet("font-size: 12px; font-weight: 600; color: #38bdf8;")
        self.lbl_active_job_status.setWordWrap(True)
        st_layout.addWidget(self.lbl_active_job_status)

        sb_layout.addWidget(status_box)
        root_layout.addWidget(self.sidebar)

        # -------------------------------------------------------------
        # Main Content Area (QStackedWidget)
        # -------------------------------------------------------------
        content_frame = QWidget(central_widget)
        cf_layout = QVBoxLayout(content_frame)
        cf_layout.setContentsMargins(0, 0, 0, 0)
        cf_layout.setSpacing(0)

        self.stack = QStackedWidget(content_frame)

        # Instantiate all 6 pages with SHARED JobState and ServiceContainer
        self.page_dashboard = DashboardPage(self.job_state, self.services, self.stack)
        self.page_tiktok = TikTokPage(self.job_state, self.services, self.stack)
        self.page_ai = AIPage(self.job_state, self.services, self.stack)
        self.page_youtube = YouTubePage(self.job_state, self.services, self.stack)
        self.page_history = HistoryPage(self.job_state, self.services, self.stack)
        self.page_settings = SettingsPage(self.job_state, self.services, self.stack)

        self.stack.addWidget(self.page_dashboard)   # Index 0
        self.stack.addWidget(self.page_tiktok)      # Index 1
        self.stack.addWidget(self.page_ai)          # Index 2
        self.stack.addWidget(self.page_youtube)     # Index 3
        self.stack.addWidget(self.page_history)     # Index 4
        self.stack.addWidget(self.page_settings)    # Index 5

        cf_layout.addWidget(self.stack)
        root_layout.addWidget(content_frame, stretch=1)

        # Set default active page: Dashboard
        self.btn_nav_dashboard.setChecked(True)
        self.stack.setCurrentIndex(0)

    def _create_nav_button(self, text: str, page_index: int) -> QPushButton:
        btn = QPushButton(text, self.sidebar)
        btn.setProperty("class", "navBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav_group.addButton(btn, page_index)
        btn.clicked.connect(lambda: self._on_nav_clicked(page_index))
        return btn

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK_THEME_QSS)

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
        # If navigating to history, refresh its data
        if index == 4:
            self.page_history.refresh_history()

    @Slot(str)
    def _on_status_changed(self, status: str) -> None:
        status_map = {
            "NEW": "Mới bắt đầu",
            "METADATA_OK": "Đã lấy thông tin",
            "DOWNLOADED": "Đã tải video",
            "CONTENT_READY": "Nội dung AI sẵn sàng",
            "UPLOADING": "Đang tải lên YouTube...",
            "UPLOADED": "Đã xuất bản YouTube",
            "DRY_RUN": "Đã chạy thử (chưa đăng YouTube)",
            "FAILED": "Thất bại",
            "CANCELLED": "Đã hủy tác vụ",
        }
        self.lbl_active_job_status.setText(status_map.get(status, status))

    @Slot(str)
    def _on_video_ready(self, path: str) -> None:
        self.lbl_active_job_status.setText("Video sẵn sàng")


def run_app() -> int:
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    import sys
    sys.exit(run_app())

