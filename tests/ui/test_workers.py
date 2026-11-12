"""Unit tests for background workers and thread safety."""

from pathlib import Path
from time import sleep

import pytest
from PySide6.QtCore import QThreadPool

from app.contracts import UploadRequest, VideoMeta
from app.services.fakes import (
    FakeContentGenerator, FakeTikTokService, FakeYouTubeService,
)
from app.workers import (
    DownloadVideoWorker, FetchMetaWorker, GenerateContentWorker, TaskWorker,
    UploadYouTubeWorker,
)


def test_task_worker_success(qtbot):
    pool = QThreadPool.globalInstance()

    def sample_task(on_progress, cancel_token):
        on_progress(0.5)
        return "SUCCESS_RESULT"

    worker = TaskWorker(sample_task)

    results = []
    progress_values = []

    worker.signals.progress.connect(progress_values.append)
    worker.signals.finished.connect(results.append)

    with qtbot.waitSignal(worker.signals.finished, timeout=2000):
        pool.start(worker)

    assert results == ["SUCCESS_RESULT"]
    assert 0.5 in progress_values


def test_task_worker_error(qtbot):
    pool = QThreadPool.globalInstance()

    def failing_task(on_progress, cancel_token):
        raise ValueError("Lỗi thử nghiệm cố ý")

    worker = TaskWorker(failing_task)
    errors = []
    worker.signals.error.connect(errors.append)

    with qtbot.waitSignal(worker.signals.error, timeout=2000):
        pool.start(worker)

    assert len(errors) == 1
    assert "Lỗi thử nghiệm cố ý" in errors[0]


def test_task_worker_cancellation(qtbot):
    pool = QThreadPool.globalInstance()

    def slow_task(on_progress, cancel_token):
        for _ in range(100):
            cancel_token.raise_if_cancelled()
            sleep(0.01)
        return "NEVER"

    worker = TaskWorker(slow_task)
    cancelled_signals = []
    worker.signals.cancelled.connect(lambda: cancelled_signals.append(True))

    pool.start(worker)
    sleep(0.02)
    worker.cancel()

    qtbot.waitUntil(lambda: len(cancelled_signals) == 1, timeout=2000)
    assert cancelled_signals == [True]


def test_service_workers_with_fakes(qtbot, tmp_path):
    pool = QThreadPool.globalInstance()
    tiktok_service = FakeTikTokService()
    youtube_service = FakeYouTubeService()
    generator = FakeContentGenerator()

    # 1. FetchMetaWorker
    meta_worker = FetchMetaWorker(tiktok_service, "https://tiktok.com/@demo/video/1")
    meta_results = []
    meta_worker.signals.finished.connect(meta_results.append)

    with qtbot.waitSignal(meta_worker.signals.finished, timeout=2000):
        pool.start(meta_worker)

    assert len(meta_results) == 1
    meta = meta_results[0]
    assert isinstance(meta, VideoMeta)

    # 2. DownloadVideoWorker
    dl_worker = DownloadVideoWorker(tiktok_service, meta, tmp_path)
    dl_results = []
    dl_worker.signals.finished.connect(dl_results.append)

    with qtbot.waitSignal(dl_worker.signals.finished, timeout=2000):
        pool.start(dl_worker)

    assert len(dl_results) == 1
    assert dl_results[0].path.name == "demo-001.mp4"

    # 3. GenerateContentWorker
    gen_worker = GenerateContentWorker(generator, meta)
    gen_results = []
    gen_worker.signals.finished.connect(gen_results.append)

    with qtbot.waitSignal(gen_worker.signals.finished, timeout=2000):
        pool.start(gen_worker)

    assert len(gen_results) == 1
    assert gen_results[0].title == "Tiêu đề mẫu — chỉ dùng phát triển"

    # 4. UploadYouTubeWorker
    youtube_service.connect()
    dummy_req = UploadRequest(
        path=tmp_path / "demo.mp4",
        title="Test Title",
        description="Test Desc",
        tags=["test"],
        privacy="private",
        made_for_kids=False,
        rights_confirmed=True,
    )
    up_worker = UploadYouTubeWorker(youtube_service, dummy_req)
    up_results = []
    up_worker.signals.finished.connect(up_results.append)

    with qtbot.waitSignal(up_worker.signals.finished, timeout=2000):
        pool.start(up_worker)

    assert len(up_results) == 1
    assert up_results[0].video_id == "fake-video-dev"

