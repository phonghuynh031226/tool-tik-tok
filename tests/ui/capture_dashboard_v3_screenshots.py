"""Capture screenshots for Dashboard v3 redesign across resolutions at scale 1.25 on Windows."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Ensure real Windows platform is used without offscreen forcing
if sys.platform == "win32":
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("FORCE_OFFSCREEN", None)

os.environ["QT_SCALE_FACTOR"] = "1.25"

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from app.contracts import ChannelAccount, JobStatus, VideoMeta
from app.ui.components.toast import ToastManager
from app.ui.main_window import MainWindow
from app.ui.services import ServiceContainer


def capture_all():
    app = QApplication.instance() or QApplication(sys.argv)

    out_dir = Path(".tmp/screenshots_v3")
    out_dir.mkdir(parents=True, exist_ok=True)

    resolutions = [
        ("1366x768", 1366, 768),
        ("1920x1080", 1920, 1080),
        ("1000x640", 1000, 640),
        ("1280x720", 1280, 720),
    ]

    fake_video = Path(".tmp/sample_preview.mp4")
    fake_video.parent.mkdir(parents=True, exist_ok=True)
    if not fake_video.exists() or fake_video.stat().st_size == 0:
        fake_video.write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00mp42isom")

    for res_label, width, height in resolutions:
        tag = f"{res_label}_scale125"

        # 1. Initial State (Empty)
        container1 = ServiceContainer.create_fake()
        win1 = MainWindow(services=container1)
        win1.resize(width, height)
        win1.show()
        app.processEvents()

        p1 = win1.grab()
        p1.save(str(out_dir / f"dashboard_01_initial_{tag}.png"), "PNG")
        print(f"Captured: dashboard_01_initial_{tag}.png")
        win1.close()

        # 2. Video Downloaded State (Video loaded, player shown, step 2 active)
        container2 = ServiceContainer.create_fake()
        win2 = MainWindow(services=container2)
        win2.resize(width, height)

        win2.job_state.url = "https://www.tiktok.com/@creator/video/7182938491829"
        win2.job_state.meta = VideoMeta(
            video_id="7182938491829",
            url="https://www.tiktok.com/@creator/video/7182938491829",
            title="Bí quyết quay video triệu view trong 30 giây",
            description="Hướng dẫn chi tiết từng bước cho người mới bắt đầu.",
            author="@topcreator",
            thumbnail_url=None,
            duration=35.0,
            width=1080,
            height=1920,
        )
        win2.job_state.set_local_file(fake_video)
        win2.job_state.status = JobStatus.DOWNLOADED
        win2.page_dashboard._sync_from_state()
        win2.page_dashboard.player_widget.load_video(str(fake_video))
        win2.show()
        app.processEvents()

        p2 = win2.grab()
        p2.save(str(out_dir / f"dashboard_02_video_loaded_{tag}.png"), "PNG")
        print(f"Captured: dashboard_02_video_loaded_{tag}.png")
        win2.close()

        # 3a. Step 3 Immediate Mode
        container3 = ServiceContainer.create_fake()
        win3 = MainWindow(services=container3)
        win3.resize(width, height)
        win3.job_state.set_local_file(fake_video)
        win3.job_state.title = "Bí Quyết Làm Video Shorts Triệu View 2026"
        win3.job_state.description = "Chia sẻ kinh nghiệm thực chiến từ chuyên gia sáng tạo nội dung."
        win3.job_state.status = JobStatus.CONTENT_READY
        win3.job_state.rights_confirmed = True
        win3.job_state.made_for_kids = False
        win3.page_dashboard._sync_from_state()
        win3.page_dashboard.radio_publish_now.setChecked(True)
        win3.show()
        app.processEvents()

        # Scroll to step 3
        win3.page_dashboard.scroll_area.ensureWidgetVisible(win3.page_dashboard.step3_card)
        app.processEvents()

        p3a = win3.grab()
        p3a.save(str(out_dir / f"dashboard_03a_immediate_{tag}.png"), "PNG")
        print(f"Captured: dashboard_03a_immediate_{tag}.png")

        # 3b. Step 3 Scheduled Mode with Calendar Popup Open
        win3.page_dashboard.radio_publish_schedule.setChecked(True)
        app.processEvents()
        # Open calendar popup
        picker = win3.page_dashboard.schedule_picker
        picker.btn_date.click()
        app.processEvents()

        p3b = win3.grab()
        if hasattr(picker, "_calendar_popup") and picker._calendar_popup and picker._calendar_popup.isVisible():
            popup = picker._calendar_popup
            painter = QPainter(p3b)
            rel_pos = win3.mapFromGlobal(popup.mapToGlobal(QPoint(0, 0)))
            popup_pix = popup.grab()
            painter.drawPixmap(rel_pos, popup_pix)
            painter.end()

        p3b.save(str(out_dir / f"dashboard_03b_scheduled_calendar_{tag}.png"), "PNG")
        print(f"Captured: dashboard_03b_scheduled_calendar_{tag}.png")
        if hasattr(picker, "_calendar_popup") and picker._calendar_popup:
            picker._calendar_popup.close()
        win3.close()

    print(f"\nAll screenshots generated in: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(capture_all())
