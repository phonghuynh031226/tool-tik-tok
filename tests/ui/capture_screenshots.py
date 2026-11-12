"""Script to visually capture and inspect all UI pages at 1080p and 720p."""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QScrollArea

from app.contracts import GeneratedContent, JobStatus, UploadRequest, VideoMeta
from app.ui.components import UploadConfirmDialog
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def capture_all_screenshots():
    # Clear offscreen to allow native Windows font rasterization (Segoe UI, Vietnamese diacritics)
    if os.environ.get("FORCE_OFFSCREEN") != "1":
        os.environ.pop("QT_QPA_PLATFORM", None)

    app = QApplication.instance() or QApplication(sys.argv)

    out_dir = Path(".tmp/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    container = ServiceContainer.create_fake()

    # Add rich mock history data for screenshot inspection
    container.history.add({
        "video_id": "vid-demo-001",
        "title": "Mẹo làm video Shorts triệu view trong 1 phút",
        "url": "https://www.youtube.com/watch?v=vid-demo-001",
        "status": JobStatus.UPLOADED,
        "privacy": "private",
        "file_path": str(Path(".tmp/downloads/demo1.mp4")),
        "created_at": "2026-11-12 18:30:00",
    })
    container.history.add({
        "video_id": "vid-demo-002",
        "title": "Tổng hợp khoảnh khắc hài hước thú cưng #shorts",
        "url": "",
        "status": JobStatus.CONTENT_READY,
        "privacy": "unlisted",
        "file_path": str(Path(".tmp/downloads/demo2.mp4")),
        "created_at": "2026-11-12 19:15:00",
    })
    container.history.add({
        "video_id": "vid-demo-003",
        "title": "Review quán ăn ngon quận 1 giá sinh viên",
        "url": "",
        "status": JobStatus.FAILED,
        "privacy": "private",
        "file_path": "",
        "created_at": "2026-11-12 19:45:00",
    })

    window = MainWindow(services=container)

    # Populate job state with realistic preview data
    window.job_state.url = "https://www.tiktok.com/@creator/video/7182938491829"
    window.job_state.meta = VideoMeta(
        video_id="7182938491829",
        url="https://www.tiktok.com/@creator/video/7182938491829",
        title="Hướng dẫn làm video Shorts triệu view siêu nhanh",
        description="Bí quyết tăng tương tác cực đỉnh cho kênh mới.",
        author="@creator_pro",
        thumbnail_url=None,
        duration=45.0,
        width=1080,
        height=1920,
    )
    window.job_state.title = "Bí Quyết Làm Video Shorts Triệu View Siêu Nhanh 2026 #Shorts"
    window.job_state.description = (
        "Khám phá ngay công thức tối ưu hóa nội dung video ngắn giúp kéo hàng triệu lượt xem "
        "cho kênh của bạn chỉ trong vòng 30 ngày!"
    )
    window.job_state.hashtags = ["shorts", "trending", "youtubecreators", "viral"]
    window.job_state.tags = ["shorts", "cách làm video", "tiktok việt nam", "mẹo hay"]
    window.job_state.rights_confirmed = True
    window.job_state.made_for_kids = False

    pages = [
        ("dashboard", 0),
        ("tiktok", 1),
        ("ai", 2),
        ("youtube", 3),
        ("history", 4),
        ("settings", 5),
    ]

    resolutions = [
        ("1080p", 1920, 1080),
        ("720p", 1280, 720),
    ]

    captured_files = []

    for res_name, width, height in resolutions:
        window.resize(width, height)
        window.show()
        app.processEvents()

        for page_name, idx in pages:
            window.stack.setCurrentIndex(idx)
            app.processEvents()

            # Render grab
            pixmap = window.grab()
            save_path = out_dir / f"{page_name}_{res_name}.png"
            pixmap.save(str(save_path), "PNG")
            captured_files.append(save_path)
            print(f"Captured: {save_path.name} ({width}x{height})")

            # For dashboard, also capture scrolled down to show steps 3 and 4
            if page_name == "dashboard":
                dashboard = window.page_dashboard
                scroll_area = dashboard.findChild(QScrollArea)
                if scroll_area:
                    scroll_area.verticalScrollBar().setValue(
                        scroll_area.verticalScrollBar().maximum()
                    )
                    app.processEvents()
                    scrolled_pixmap = window.grab()
                    scrolled_path = out_dir / f"dashboard_step3_step4_{res_name}.png"
                    scrolled_pixmap.save(str(scrolled_path), "PNG")
                    captured_files.append(scrolled_path)
                    print(f"Captured: {scrolled_path.name}")
                    # reset scroll back to top
                    scroll_area.verticalScrollBar().setValue(0)
                    app.processEvents()

            # For settings, also capture scrolled down to show Storage and yt-dlp update
            if page_name == "settings":
                settings_page = window.page_settings
                scroll_area = settings_page.findChild(QScrollArea)
                if scroll_area:
                    scroll_area.verticalScrollBar().setValue(
                        scroll_area.verticalScrollBar().maximum()
                    )
                    app.processEvents()
                    scrolled_pixmap = window.grab()
                    scrolled_path = out_dir / f"settings_storage_{res_name}.png"
                    scrolled_pixmap.save(str(scrolled_path), "PNG")
                    captured_files.append(scrolled_path)
                    print(f"Captured: {scrolled_path.name}")
                    scroll_area.verticalScrollBar().setValue(0)
                    app.processEvents()

        # Capture confirmation dialog (standard) at this resolution
        req = UploadRequest(
            path=Path(".tmp/downloads/demo.mp4"),
            title=window.job_state.title,
            description=window.job_state.description,
            tags=window.job_state.tags,
            privacy="private",
            made_for_kids=False,
            rights_confirmed=True,
        )
        dialog = UploadConfirmDialog(req, "Kênh mẫu DEV/TEST", "fake-channel-dev", window, dry_run=False)
        dialog.show()
        app.processEvents()
        dlg_pixmap = dialog.grab()
        dlg_path = out_dir / f"confirm_dialog_{res_name}.png"
        dlg_pixmap.save(str(dlg_path), "PNG")
        captured_files.append(dlg_path)
        print(f"Captured: {dlg_path.name}")
        dialog.close()

        # Capture confirmation dialog (dry-run) at this resolution
        dialog_dry = UploadConfirmDialog(req, "Kênh mẫu DEV/TEST", "fake-channel-dev", window, dry_run=True)
        dialog_dry.show()
        app.processEvents()
        dlg_dry_pixmap = dialog_dry.grab()
        dlg_dry_path = out_dir / f"confirm_dialog_dry_run_{res_name}.png"
        dlg_dry_pixmap.save(str(dlg_dry_path), "PNG")
        captured_files.append(dlg_dry_path)
        print(f"Captured: {dlg_dry_path.name}")
        dialog_dry.close()

    print(f"\nAll {len(captured_files)} screenshots captured successfully in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(capture_all_screenshots())
