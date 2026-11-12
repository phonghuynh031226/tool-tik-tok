"""Unit tests for JobState shared object."""

from pathlib import Path

import pytest

from app.contracts import DownloadResult, GeneratedContent, JobStatus, VideoMeta
from app.ui.state import JobState


def test_job_state_initial_defaults():
    state = JobState()
    assert state.url == ""
    assert state.meta is None
    assert state.download_result is None
    assert state.local_video_path is None
    assert state.title == ""
    assert state.description == ""
    assert state.privacy == "private"
    assert state.made_for_kids is None  # Mandatory: NOT chosen initially
    assert state.rights_confirmed is False
    assert state.status == JobStatus.NEW


def test_can_upload_validation(tmp_path):
    state = JobState()

    # 1. No video file
    can, reason = state.can_upload()
    assert not can
    assert "Chưa có file video" in reason

    # Create dummy local file
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"dummy")
    state.set_local_file(fake_video)

    # 2. No title
    state.title = ""
    can, reason = state.can_upload()
    assert not can
    assert "Tiêu đề video không được để trống" in reason

    # 3. Title too long (>100 chars)
    state.title = "A" * 101
    can, reason = state.can_upload()
    assert not can
    assert "100 ký tự" in reason

    state.title = "Tiêu đề hợp lệ"

    # 4. made_for_kids is None (not selected yet)
    state.made_for_kids = None
    can, reason = state.can_upload()
    assert not can
    assert "đối tượng người xem" in reason

    state.made_for_kids = False

    # 5. rights_confirmed is False
    state.rights_confirmed = False
    can, reason = state.can_upload()
    assert not can
    assert "quyền sử dụng" in reason

    # 6. All requirements met
    state.rights_confirmed = True
    can, reason = state.can_upload()
    assert can
    assert reason == ""

    # Build upload request
    req = state.build_upload_request()
    assert req.path == fake_video
    assert req.title == "Tiêu đề hợp lệ"
    assert req.privacy == "private"
    assert req.made_for_kids is False
    assert req.rights_confirmed is True


def test_restore_original():
    state = JobState()
    state.meta = VideoMeta(
        video_id="vid1",
        url="https://tiktok.com/vid1",
        title="Tiêu đề gốc ban đầu",
        description="Mô tả gốc ban đầu",
        author="Tác giả",
        thumbnail_url=None,
        duration=10.0,
        width=1080,
        height=1920,
    )

    assert state.title == "Tiêu đề gốc ban đầu"
    assert state.description == "Mô tả gốc ban đầu"

    # AI rewrites title and description
    state.set_generated_content(
        GeneratedContent(
            title="Tiêu đề AI mới toanh",
            description="Mô tả AI mới toanh",
            hashtags=["short", "viral"],
            tags=["demo"],
        )
    )
    assert state.title == "Tiêu đề AI mới toanh"
    assert state.description == "Mô tả AI mới toanh"

    # User clicks restore original
    state.restore_original()
    assert state.title == "Tiêu đề gốc ban đầu"
    assert state.description == "Mô tả gốc ban đầu"

