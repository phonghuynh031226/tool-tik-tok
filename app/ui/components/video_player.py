"""Video player component using QtMultimedia."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import os

from PySide6.QtCore import QTime, QUrl, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QStackedLayout, QVBoxLayout,
    QWidget,
)


from app.ui import i18n as _i18n
class VideoPlayerWidget(QWidget):
    """Integrated video player with play/pause, time slider and status display."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_path: Optional[Path] = None

        # Multimedia backend
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)

        # Layout setup
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Video / Placeholder / Thumbnail Stack
        self.screen_container = QWidget(self)
        self.screen_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.screen_container.setMinimumHeight(200)
        self.screen_container.setMaximumHeight(320)
        self.video_widget.setMaximumHeight(320)
        self.stack_layout = QStackedLayout(self.screen_container)

        # Placeholder when no video
        self.placeholder = _i18n.ui(QLabel("Chưa có video\n(Dán liên kết TikTok và bấm 'Tải video' để xem trước)", self))
        self.placeholder.setObjectName("videoPlaceholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.stack_layout.addWidget(self.placeholder)

        # Thumbnail view (if available before playback)
        self.thumbnail_label = QLabel(self)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setMaximumHeight(320)
        self.stack_layout.addWidget(self.thumbnail_label)

        # Active video view
        self.stack_layout.addWidget(self.video_widget)
        self.stack_layout.setCurrentWidget(self.placeholder)

        main_layout.addWidget(self.screen_container, stretch=1)

        # Control Bar
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(4, 4, 4, 4)
        controls_layout.setSpacing(10)

        self.btn_play_pause = _i18n.ui(QPushButton("▶ Phát", self))
        self.btn_play_pause.setFixedWidth(80)
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        controls_layout.addWidget(self.btn_play_pause)

        self.time_label_current = QLabel("00:00", self)
        self.time_label_current.setProperty("class", "hintLabel")
        controls_layout.addWidget(self.time_label_current)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self._set_position)
        controls_layout.addWidget(self.slider, stretch=1)

        self.time_label_total = QLabel("00:00", self)
        self.time_label_total.setProperty("class", "hintLabel")
        controls_layout.addWidget(self.time_label_total)

        main_layout.addLayout(controls_layout)

        # Connect player signals
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)

    def set_thumbnail(self, thumbnail_path: Path | str) -> None:
        """Display video thumbnail while paused/stopped."""
        p = Path(thumbnail_path)
        if p.exists() and p.is_file():
            from PySide6.QtGui import QPixmap
            pix = QPixmap(str(p))
            if not pix.isNull():
                self.thumbnail_label.setPixmap(pix.scaled(
                    self.screen_container.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self.stack_layout.setCurrentWidget(self.thumbnail_label)

    def load_video(self, path: Path | str, thumbnail_path: Optional[Path | str] = None) -> None:
        """Load an MP4 file into the player and prime the first frame at ~100ms."""
        p = Path(path)
        self._current_path = p
        is_offscreen = os.environ.get("QT_QPA_PLATFORM") == "offscreen" or (
            QGuiApplication.platformName() == "offscreen" if QGuiApplication.instance() else False
        )
        is_valid_mp4 = False
        if p.exists() and p.stat().st_size > 256:
            try:
                with open(p, "rb") as f:
                    hdr = f.read(64)
                    is_valid_mp4 = b"ftyp" in hdr
            except Exception:
                is_valid_mp4 = False

        if thumbnail_path:
            self.set_thumbnail(thumbnail_path)

        if p.exists() and not is_offscreen and is_valid_mp4:
            try:
                self.player.setSource(QUrl.fromLocalFile(str(p.resolve())))
                self.stack_layout.setCurrentWidget(self.video_widget)
                self.btn_play_pause.setEnabled(True)
                self.slider.setEnabled(True)

                # Show first video frame (seek ~100ms and pause)
                def _prime_frame(status):
                    if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
                        self.player.setPosition(100)
                        self.player.pause()
                        try:
                            self.player.mediaStatusChanged.disconnect(_prime_frame)
                        except Exception:
                            pass

                self.player.mediaStatusChanged.connect(_prime_frame)
                self.player.setPosition(100)
                self.player.pause()
            except Exception:
                self.placeholder.setText(f"Video: {p.name}")
                self.stack_layout.setCurrentWidget(self.placeholder)
                self.btn_play_pause.setEnabled(True)
        else:
            # File might be a virtual fake in test or running in headless mode
            self.placeholder.setText(f"Video: {p.name}")
            self.stack_layout.setCurrentWidget(self.placeholder)
            self.btn_play_pause.setEnabled(True)

    def clear(self) -> None:
        """Reset player state."""
        self.player.stop()
        self.player.setSource(QUrl())
        self._current_path = None
        self.thumbnail_label.clear()
        _i18n.set_text(self.placeholder, "Chưa có video\n(Dán liên kết TikTok và bấm 'Tải video' để xem trước)")
        self.stack_layout.setCurrentWidget(self.placeholder)
        self.btn_play_pause.setEnabled(False)
        _i18n.set_text(self.btn_play_pause, "▶ Phát")
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.time_label_current.setText("00:00")
        self.time_label_total.setText("00:00")

    @Slot()
    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.stack_layout.setCurrentWidget(self.video_widget)
            self.player.play()

    @Slot(int)
    def _on_position_changed(self, position: int) -> None:
        if not self.slider.isSliderDown():
            duration = self.player.duration()
            if duration > 0:
                self.slider.setValue(int(position * 1000 / duration))
        self.time_label_current.setText(self._format_time(position))

    @Slot(int)
    def _on_duration_changed(self, duration: int) -> None:
        self.time_label_total.setText(self._format_time(duration))

    @Slot(int)
    def _set_position(self, value: int) -> None:
        duration = self.player.duration()
        if duration > 0:
            target_ms = int(value * duration / 1000)
            self.player.setPosition(target_ms)

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            _i18n.set_text(self.btn_play_pause, "⏸ Tạm dừng")
        else:
            _i18n.set_text(self.btn_play_pause, "▶ Phát")

    @staticmethod
    def _format_time(ms: int) -> str:
        seconds = max(0, ms // 1000)
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins:02d}:{secs:02d}"

