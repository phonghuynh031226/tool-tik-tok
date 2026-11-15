"""Custom Schedule Picker with Vietnamese Calendar Popup and Quick Chips."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from typing import Optional

from PySide6.QtCore import QDate, QEvent, QPoint, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.ui import icons, tokens
from app.ui.components.buttons import AppButton

VIETNAMESE_WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]
VIETNAMESE_WEEKDAYS_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


class CustomCalendarPopup(QFrame):
    """Full-featured dark theme calendar popup with Vietnamese day names (Monday start)."""

    date_selected = Signal(QDate)

    def __init__(self, current_date: QDate, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(310)

        self._view_year = current_date.year()
        self._view_month = current_date.month()
        self._selected_date = current_date
        self._today = QDate.currentDate()

        self._init_ui()
        self._render_calendar()

    def _init_ui(self) -> None:
        self.setObjectName("calendarPopup")
        self.setStyleSheet(f"""
            QFrame#calendarPopup {{
                background-color: {tokens.BG_CARD};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: {tokens.RADIUS_MD}px;
                padding: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header: Prev Month | Month Year | Next Month
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_prev = QPushButton("‹", self)
        self.btn_prev.setFixedSize(28, 28)
        self.btn_prev.setStyleSheet(f"""
            QPushButton {{
                background-color: {tokens.BG_INPUT};
                color: {tokens.TEXT_PRIMARY};
                border: 1px solid {tokens.BORDER_SUBTLE};
                border-radius: 4px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {tokens.BG_INPUT_HOVER};
                border-color: {tokens.PRIMARY};
            }}
        """)
        self.btn_prev.clicked.connect(self._prev_month)
        header_layout.addWidget(self.btn_prev)

        self.lbl_month_year = QLabel(self)
        self.lbl_month_year.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_month_year.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {tokens.TEXT_PRIMARY};"
        )
        header_layout.addWidget(self.lbl_month_year, stretch=1)

        self.btn_next = QPushButton("›", self)
        self.btn_next.setFixedSize(28, 28)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{
                background-color: {tokens.BG_INPUT};
                color: {tokens.TEXT_PRIMARY};
                border: 1px solid {tokens.BORDER_SUBTLE};
                border-radius: 4px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {tokens.BG_INPUT_HOVER};
                border-color: {tokens.PRIMARY};
            }}
        """)
        self.btn_next.clicked.connect(self._next_month)
        header_layout.addWidget(self.btn_next)

        layout.addLayout(header_layout)

        # Days of week header: T2 - CN
        self.week_header_layout = QHBoxLayout()
        self.week_header_layout.setSpacing(4)
        for day_name in VIETNAMESE_WEEKDAYS_SHORT:
            lbl = QLabel(day_name, self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(36, 22)
            lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {tokens.TEXT_SECONDARY};")
            self.week_header_layout.addWidget(lbl)
        layout.addLayout(self.week_header_layout)

        # Grid of days
        self.grid_widget = QWidget(self)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(4)
        layout.addWidget(self.grid_widget)

    def _render_calendar(self) -> None:
        self.lbl_month_year.setText(f"Tháng {self._view_month:02d} / {self._view_year}")

        # Clear existing grid buttons
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Monday is 0, Sunday is 6
        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdatescalendar(self._view_year, self._view_month)

        for row_idx, week in enumerate(month_days):
            for col_idx, day_date in enumerate(week):
                qdate = QDate(day_date.year, day_date.month, day_date.day)
                btn = QPushButton(str(day_date.day), self.grid_widget)
                btn.setFixedSize(36, 32)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)

                is_curr_month = (day_date.month == self._view_month)
                is_past = (qdate < self._today)
                is_selected = (qdate == self._selected_date)
                is_today = (qdate == self._today)

                if not is_curr_month:
                    btn.setStyleSheet(f"color: #334155; background: transparent; border: none; font-size: 12px;")
                    btn.setEnabled(False)
                elif is_past:
                    btn.setStyleSheet(f"color: #475569; background: transparent; border: none; font-size: 12px;")
                    btn.setEnabled(False)
                elif is_selected:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {tokens.PRIMARY};
                            color: #ffffff;
                            border: none;
                            border-radius: 6px;
                            font-size: 12px;
                            font-weight: bold;
                        }}
                    """)
                    btn.clicked.connect(lambda checked=False, d=qdate: self._on_date_clicked(d))
                elif is_today:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: transparent;
                            color: #38bdf8;
                            border: 1px solid #38bdf8;
                            border-radius: 6px;
                            font-size: 12px;
                            font-weight: bold;
                        }}
                        QPushButton:hover {{
                            background-color: {tokens.BG_INPUT_HOVER};
                        }}
                    """)
                    btn.clicked.connect(lambda checked=False, d=qdate: self._on_date_clicked(d))
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: transparent;
                            color: {tokens.TEXT_PRIMARY};
                            border: none;
                            border-radius: 6px;
                            font-size: 12px;
                        }}
                        QPushButton:hover {{
                            background-color: {tokens.BG_INPUT_HOVER};
                        }}
                    """)
                    btn.clicked.connect(lambda checked=False, d=qdate: self._on_date_clicked(d))

                self.grid_layout.addWidget(btn, row_idx, col_idx)

    def _prev_month(self) -> None:
        if self._view_month == 1:
            self._view_month = 12
            self._view_year -= 1
        else:
            self._view_month -= 1
        self._render_calendar()

    def _next_month(self) -> None:
        if self._view_month == 12:
            self._view_month = 1
            self._view_year += 1
        else:
            self._view_month += 1
        self._render_calendar()

    def _on_date_clicked(self, qdate: QDate) -> None:
        self._selected_date = qdate
        self.date_selected.emit(qdate)
        self.close()

    def show_below(self, target_widget: QWidget) -> None:
        """Position and display the popup right under the target widget."""
        pos = target_widget.mapToGlobal(QPoint(0, target_widget.height() + 4))
        self.move(pos)
        self.show()


class SchedulePickerWidget(QWidget):
    """Complete scheduling control with Vietnamese date button, hour/min spinners, quick chips, and live validation."""

    datetime_changed = Signal(object)  # emits Optional[datetime] (UTC)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._target_dt: datetime = self._default_time()
        self._calendar_popup: Optional[CustomCalendarPopup] = None
        self._is_valid: bool = True

        self._init_ui()
        self._update_display()

    @staticmethod
    def _default_time() -> datetime:
        dt = datetime.now() + timedelta(hours=1)
        return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Row 1: Date Button + Hour / Minute selectors + Timezone
        picker_row = QHBoxLayout()
        picker_row.setSpacing(8)

        self.btn_date = QPushButton(self)
        self.btn_date.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_date.setMinimumHeight(tokens.HEIGHT_INPUT_MD)
        self.btn_date.setStyleSheet(f"""
            QPushButton {{
                background-color: {tokens.BG_INPUT};
                color: {tokens.TEXT_PRIMARY};
                border: 1px solid {tokens.BORDER_DEFAULT};
                border-radius: {tokens.RADIUS_MD}px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {tokens.BORDER_HOVER};
                background-color: {tokens.BG_INPUT_HOVER};
            }}
        """)
        self.btn_date.clicked.connect(self._open_calendar_popup)
        picker_row.addWidget(self.btn_date, stretch=3)

        # Hour combo
        self.combo_hour = QComboBox(self)
        for h in range(24):
            self.combo_hour.addItem(f"{h:02d}", h)
        self.combo_hour.setFixedWidth(64)
        self.combo_hour.currentIndexChanged.connect(self._on_time_component_changed)
        picker_row.addWidget(self.combo_hour)

        lbl_colon = QLabel(":", self)
        lbl_colon.setStyleSheet("font-weight: bold; font-size: 14px; color: #94a3b8;")
        picker_row.addWidget(lbl_colon)

        # Minute combo (5 min step)
        self.combo_minute = QComboBox(self)
        for m in range(0, 60, 5):
            self.combo_minute.addItem(f"{m:02d}", m)
        self.combo_minute.setFixedWidth(64)
        self.combo_minute.currentIndexChanged.connect(self._on_time_component_changed)
        picker_row.addWidget(self.combo_minute)

        # Timezone label
        tz_str = datetime.now().astimezone().strftime("%z")
        tz_formatted = f"GMT{tz_str[:3]}:{tz_str[3:]}" if len(tz_str) == 5 else "GMT+7"
        self.lbl_timezone = QLabel(f"Múi giờ máy: {tz_formatted}", self)
        self.lbl_timezone.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 12px;")
        picker_row.addWidget(self.lbl_timezone)

        picker_row.addStretch()
        layout.addLayout(picker_row)

        # Row 2: Quick suggestion chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)

        lbl_quick = QLabel("Gợi ý nhanh:", self)
        lbl_quick.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px; font-weight: 500;")
        chips_row.addWidget(lbl_quick)

        self.btn_chip_plus_1h = self._create_chip("+1 giờ", self._chip_plus_1h)
        chips_row.addWidget(self.btn_chip_plus_1h)

        self.btn_chip_tonight = self._create_chip("Tối nay 20:00", self._chip_tonight)
        chips_row.addWidget(self.btn_chip_tonight)

        self.btn_chip_tomorrow = self._create_chip("Sáng mai 08:00", self._chip_tomorrow)
        chips_row.addWidget(self.btn_chip_tomorrow)

        self.btn_chip_weekend = self._create_chip("Cuối tuần 09:00", self._chip_weekend)
        chips_row.addWidget(self.btn_chip_weekend)

        chips_row.addStretch()
        layout.addLayout(chips_row)

        # Row 3: Live Summary & Validation Notice
        self.lbl_summary = QLabel(self)
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(self.lbl_summary)

        # Row 4: YouTube Notice
        lbl_notice = QLabel(
            "YouTube sẽ tự động công khai video đúng thời điểm hẹn, bạn không cần giữ ứng dụng chạy.",
            self,
        )
        lbl_notice.setWordWrap(True)
        lbl_notice.setStyleSheet(f"color: {tokens.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(lbl_notice)

    def _create_chip(self, label: str, callback) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #1e2538;
                color: #cbd5e1;
                border: 1px solid #2d3748;
                border-radius: 12px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {tokens.PRIMARY_BG};
                color: #ffffff;
                border-color: {tokens.PRIMARY};
            }}
        """)
        btn.clicked.connect(callback)
        return btn

    def _open_calendar_popup(self) -> None:
        qdate = QDate(self._target_dt.year, self._target_dt.month, self._target_dt.day)
        self._calendar_popup = CustomCalendarPopup(qdate, self)
        self._calendar_popup.date_selected.connect(self._on_date_selected)
        self._calendar_popup.show_below(self.btn_date)

    def _on_date_selected(self, qdate: QDate) -> None:
        self._target_dt = self._target_dt.replace(
            year=qdate.year(),
            month=qdate.month(),
            day=qdate.day(),
        )
        self._update_display()

    def _on_time_component_changed(self) -> None:
        hour = self.combo_hour.currentData() or 0
        minute = self.combo_minute.currentData() or 0
        self._target_dt = self._target_dt.replace(hour=hour, minute=minute)
        self._update_display()

    def _chip_plus_1h(self) -> None:
        dt = datetime.now() + timedelta(hours=1)
        dt = dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
        self.set_datetime(dt)

    def _chip_tonight(self) -> None:
        dt = datetime.now().replace(hour=20, minute=0, second=0, microsecond=0)
        if dt < datetime.now() + timedelta(minutes=10):
            # If past or too close, schedule tomorrow 20:00
            dt += timedelta(days=1)
        self.set_datetime(dt)

    def _chip_tomorrow(self) -> None:
        dt = (datetime.now() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        self.set_datetime(dt)

    def _chip_weekend(self) -> None:
        now = datetime.now()
        days_ahead = 5 - now.weekday()  # Saturday is 5
        if days_ahead <= 0:
            days_ahead += 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
        self.set_datetime(dt)

    def _update_chips_visibility(self) -> None:
        now = datetime.now()
        tonight = now.replace(hour=20, minute=0, second=0, microsecond=0)
        # Hide or dim 'Tối nay' if already past 19:50
        if now >= tonight - timedelta(minutes=10):
            self.btn_chip_tonight.setVisible(False)
        else:
            self.btn_chip_tonight.setVisible(True)

    def _update_display(self) -> None:
        self._update_chips_visibility()

        # Update Date button text
        weekday_name = VIETNAMESE_WEEKDAYS[self._target_dt.weekday()]
        date_str = f"📅 {weekday_name}, {self._target_dt.strftime('%d/%m/%Y')}"
        self.btn_date.setText(date_str)

        # Update Hour/Minute combo boxes without triggering redundant signals
        self.combo_hour.blockSignals(True)
        h_idx = self.combo_hour.findData(self._target_dt.hour)
        if h_idx >= 0:
            self.combo_hour.setCurrentIndex(h_idx)
        self.combo_hour.blockSignals(False)

        self.combo_minute.blockSignals(True)
        # round minute to nearest 5
        m_val = (self._target_dt.minute // 5) * 5
        m_idx = self.combo_minute.findData(m_val)
        if m_idx >= 0:
            self.combo_minute.setCurrentIndex(m_idx)
        self.combo_minute.blockSignals(False)

        # Validation: 10 minutes <= delta <= 365 days
        now = datetime.now()
        delta = self._target_dt - now
        total_seconds = delta.total_seconds()

        tz_str = now.astimezone().strftime("%z")
        tz_fmt = f"GMT{tz_str[:3]}:{tz_str[3:]}" if len(tz_str) == 5 else "GMT+7"

        if total_seconds < 600:  # < 10 min
            self._is_valid = False
            self.lbl_summary.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600;")
            rem_min = int(total_seconds // 60)
            if rem_min <= 0:
                self.lbl_summary.setText("⚠️ Thời điểm hẹn phải nằm trong tương lai (ít nhất cách 10 phút).")
            else:
                self.lbl_summary.setText(f"⚠️ Lịch hẹn phải cách hiện tại ít nhất 10 phút (hiện chỉ còn {rem_min} phút).")
            self.datetime_changed.emit(None)
        elif total_seconds > 365 * 86400:  # > 365 days
            self._is_valid = False
            self.lbl_summary.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600;")
            self.lbl_summary.setText("⚠️ Lịch hẹn không được vượt quá 365 ngày kể từ hôm nay.")
            self.datetime_changed.emit(None)
        else:
            self._is_valid = True
            self.lbl_summary.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")

            days = int(total_seconds // 86400)
            hours = int((total_seconds % 86400) // 3600)
            mins = int((total_seconds % 3600) // 60)

            time_parts = []
            if days > 0:
                time_parts.append(f"{days} ngày")
            if hours > 0:
                time_parts.append(f"{hours} giờ")
            if mins > 0 or not time_parts:
                time_parts.append(f"{mins} phút")
            remaining_str = " ".join(time_parts)

            dt_fmt = self._target_dt.strftime("%H:%M")
            self.lbl_summary.setText(
                f"Sẽ công khai lúc {dt_fmt} {weekday_name} {self._target_dt.strftime('%d/%m/%Y')} ({tz_fmt}), còn {remaining_str}."
            )
            # Emit UTC datetime
            utc_dt = self._target_dt.astimezone(timezone.utc)
            self.datetime_changed.emit(utc_dt)

    def is_valid(self) -> bool:
        return self._is_valid

    def get_datetime(self) -> Optional[datetime]:
        """Return scheduled datetime in UTC if valid, None if invalid."""
        if not self._is_valid:
            return None
        return self._target_dt.astimezone(timezone.utc)

    def set_datetime(self, dt: datetime) -> None:
        """Set datetime from a local or UTC datetime."""
        if dt.tzinfo is not None:
            local_dt = dt.astimezone()
            self._target_dt = local_dt.replace(tzinfo=None)
        else:
            self._target_dt = dt
        self._update_display()

