from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import SegmentedWidget, TransparentToolButton
except Exception:
    SegmentedWidget = None
    TransparentToolButton = None

from database.db import SessionLocal
from database.models.appointment import (
    APPOINTMENT_STATUS_SCHEDULED,
    Appointment,
)
from database.models.missionary import Missionary
from services.appointment_service import AppointmentService
from ui.foundation import (
    BodyLabel,
    FLUENT_AVAILABLE,
    InfoLevel,
    FilterBar,
    PageHeader,
    StatCard,
    StrongBodyLabel,
    create_header_card,
    create_info_badge,
    create_pill_button,
    create_button,
    create_card,
    create_combo_box,
    create_pivot,
    create_scroll_area,
    create_search_edit,
    divider,
    fluent_icon,
    show_message,
)
from utils.logger import logger


APPOINTMENT_FIELDS = [
    ("interpol_appointment_date", "Interpol", "#7C3AED"),
    ("biometric_appointment_date", "Biometric", "#D97706"),
    ("pickup_appointment_date", "Pickup", "#059669"),
]

BUCKET_ORDER = ["overdue", "today", "next_7", "later"]
BUCKET_LABELS = {
    "overdue": "Overdue",
    "today": "Today",
    "next_7": "Next 7 Days",
    "later": "Later",
}
BUCKET_TONES = {
    "overdue": "danger",
    "today": "warning",
    "next_7": "caution",
    "later": "success",
}
BUCKET_INFO_LEVELS = {
    "overdue": InfoLevel.ERROR,
    "today": InfoLevel.WARNING,
    "next_7": InfoLevel.ATTENTION,
    "later": InfoLevel.SUCCESS,
}
SUMMARY_COLORS = {
    "overdue": "#DC2626",
    "today": "#D97706",
    "this_week": "#2563EB",
    "total": "#059669",
}

CALENDAR_MODE_WEEK = "week"
CALENDAR_MODE_MONTH = "month"
TAB_CALENDAR = "calendar"
TAB_HISTORY = "history"
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class AppointmentItem:
    missionary_id: int
    full_name: str
    current_stage: str
    date: date
    type: str
    color: str
    field: str
    days_offset: int
    bucket: str
    appointment_id: int = 0


def appointment_bucket(appt_date, today):
    days_offset = (appt_date - today).days

    if days_offset < 0:
        return "overdue"
    if days_offset == 0:
        return "today"
    if days_offset <= 7:
        return "next_7"
    return "later"


def appointment_distance_text(days_offset):
    if days_offset < 0:
        days = abs(days_offset)
        return f"{days} day{'s' if days != 1 else ''} overdue"
    if days_offset == 0:
        return "Due today"
    return f"In {days_offset} day{'s' if days_offset != 1 else ''}"


def week_start_for(value):
    return value - timedelta(days=value.weekday())


def month_grid_dates(year, month):
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    start = week_start_for(first_day)
    end = week_start_for(next_month - timedelta(days=1)) + timedelta(days=6)
    days = (end - start).days + 1
    return [start + timedelta(days=offset) for offset in range(days)]


def visible_range_for_mode(mode, anchor_date):
    if mode == CALENDAR_MODE_MONTH:
        return month_grid_dates(anchor_date.year, anchor_date.month)

    start = week_start_for(anchor_date)
    return [start + timedelta(days=offset) for offset in range(7)]


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)

BUCKET_ORDER = ["overdue", "today", "next_7", "later"]
BUCKET_LABELS = {
    "overdue": "Overdue",
    "today": "Today",
    "next_7": "Next 7 Days",
    "later": "Later",
}
BUCKET_TONES = {
    "overdue": "danger",
    "today": "warning",
    "next_7": "caution",
    "later": "success",
}
SUMMARY_COLORS = {
    "overdue": "#DC2626",
    "today": "#D97706",
    "this_week": "#2563EB",
    "total": "#059669",
}

CALENDAR_MODE_WEEK = "week"
CALENDAR_MODE_MONTH = "month"
TAB_CALENDAR = "calendar"
TAB_HISTORY = "history"
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def appointment_bucket(appt_date, today):
    days_offset = (appt_date - today).days

    if days_offset < 0:
        return "overdue"
    if days_offset == 0:
        return "today"
    if days_offset <= 7:
        return "next_7"
    return "later"


def appointment_distance_text(days_offset):
    if days_offset < 0:
        days = abs(days_offset)
        return f"{days} day{'s' if days != 1 else ''} overdue"
    if days_offset == 0:
        return "Due today"
    return f"In {days_offset} day{'s' if days_offset != 1 else ''}"


def week_start_for(value):
    return value - timedelta(days=value.weekday())


def month_grid_dates(year, month):
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    start = week_start_for(first_day)
    end = week_start_for(next_month - timedelta(days=1)) + timedelta(days=6)
    days = (end - start).days + 1
    return [start + timedelta(days=offset) for offset in range(days)]


def visible_range_for_mode(mode, anchor_date):
    if mode == CALENDAR_MODE_MONTH:
        return month_grid_dates(anchor_date.year, anchor_date.month)

    start = week_start_for(anchor_date)
    return [start + timedelta(days=offset) for offset in range(7)]


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


class CalendarPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.setObjectName("CalendarPage")
        self.main_window = main_window
        self._appointments = []
        self._calendar_mode = CALENDAR_MODE_WEEK
        self._anchor_date = date.today()
        self._calendar_search_text = ""
        self._calendar_type_filter = "All Types"
        self._history_exact_date = None
        self._selected_tab = TAB_CALENDAR

        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self._count_label = QLabel("")
        self._count_label.setObjectName("MutedText")

        header = PageHeader(
            "Appointments Calendar",
            "Scheduled Interpol, biometric, and pickup citas.",
            [self._count_label],
        )
        outer.addWidget(header)
        outer.addWidget(divider())

        self._build_top_tabs()
        outer.addWidget(self.tab_bar)

        self.tab_stack = QStackedWidget()
        self.tab_stack.setObjectName("CalendarTabStack")
        outer.addWidget(self.tab_stack, stretch=1)

        self._build_calendar_tab()
        self._build_history_tab()
        self._select_tab(TAB_CALENDAR)

    def _build_top_tabs(self):
        self.tab_buttons = {}
        self.tab_button_group = QButtonGroup(self)
        self.tab_control = create_pivot()

        if self.tab_control is not None:
            self.tab_bar = QFrame()
            self.tab_bar.setObjectName("CalendarTopTabs")
            layout = QHBoxLayout()
            layout.setContentsMargins(32, 8, 32, 8)
            layout.setSpacing(0)
            self.tab_bar.setLayout(layout)

            self.tab_control.setObjectName("CalendarPivot")
            self.tab_control.currentItemChanged.connect(self._select_tab)
            layout.addWidget(self.tab_control)
            layout.addStretch()

            self.tab_control.addItem(
                TAB_CALENDAR,
                "Calendar",
                icon=fluent_icon("CALENDAR"),
            )
            self.tab_control.addItem(
                TAB_HISTORY,
                "History",
                icon=fluent_icon("HISTORY"),
            )
            return

        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("CalendarTopTabs")

        layout = QHBoxLayout()
        layout.setContentsMargins(32, 10, 32, 10)
        layout.setSpacing(8)
        self.tab_bar.setLayout(layout)

        self.tab_button_group.setExclusive(True)

        for key, title in [
            (TAB_CALENDAR, "Calendar"),
            (TAB_HISTORY, "History"),
        ]:
            button = QPushButton(title)
            button.setObjectName("CalendarTabButton")
            button.setCheckable(True)
            button.setFixedHeight(32)
            button.clicked.connect(
                lambda checked=False, tab_key=key:
                self._select_tab(tab_key)
            )
            self.tab_button_group.addButton(button)
            self.tab_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()

    def _build_calendar_tab(self):
        tab = QWidget()
        tab.setObjectName("PageSurface")
        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        tab.setLayout(tab_layout)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")

        content = QWidget()
        content.setObjectName("PageSurface")
        self.calendar_layout = QVBoxLayout()
        self.calendar_layout.setContentsMargins(32, 24, 32, 24)
        self.calendar_layout.setSpacing(18)
        content.setLayout(self.calendar_layout)

        scroll.setWidget(content)
        tab_layout.addWidget(scroll, stretch=1)
        self.calendar_index = self.tab_stack.addWidget(tab)

    def _build_history_tab(self):
        tab = QWidget()
        tab.setObjectName("PageSurface")
        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        tab.setLayout(tab_layout)

        self._build_history_filter_bar()
        tab_layout.addWidget(self.history_filter_bar)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")

        content = QWidget()
        content.setObjectName("PageSurface")
        self.history_layout = QVBoxLayout()
        self.history_layout.setContentsMargins(32, 24, 32, 24)
        self.history_layout.setSpacing(18)
        content.setLayout(self.history_layout)

        scroll.setWidget(content)
        tab_layout.addWidget(scroll, stretch=1)
        self.history_index = self.tab_stack.addWidget(tab)

    def _build_history_filter_bar(self):
        self.history_filter_bar = FilterBar()

        self.history_search_edit = create_search_edit("Search missionary")
        self.history_search_edit.textChanged.connect(self._render_history)
        self.history_filter_bar.add_filter(
            self.history_search_edit,
            stretch=1,
        )

        self.history_type_combo = create_combo_box()
        for label in ["All Types", "Interpol", "Biometric", "Pickup"]:
            self.history_type_combo.addItem(label, label)
        self.history_type_combo.currentIndexChanged.connect(
            lambda _=None: self._render_history()
        )
        self.history_filter_bar.add_filter(self.history_type_combo)

        self.history_status_combo = create_combo_box()
        for label, value in [
            ("All", "all"),
            ("Needs Attention", "needs_attention"),
            ("Overdue", "overdue"),
            ("Today", "today"),
            ("Next 7 Days", "next_7"),
            ("Upcoming", "upcoming"),
        ]:
            self.history_status_combo.addItem(label, value)
        self.history_status_combo.currentIndexChanged.connect(
            lambda _=None: self._render_history()
        )
        self.history_filter_bar.add_filter(self.history_status_combo)

        self.history_sort_combo = create_combo_box()
        for label, value in [
            ("Date Ascending", "asc"),
            ("Date Descending", "desc"),
        ]:
            self.history_sort_combo.addItem(label, value)
        self.history_sort_combo.currentIndexChanged.connect(
            lambda _=None: self._render_history()
        )
        self.history_filter_bar.add_filter(self.history_sort_combo)

        self.history_date_label = QLabel("")
        self.history_date_label.setObjectName("CalendarHistoryDateFilter")
        self.history_date_label.setVisible(False)
        self.history_filter_bar.add_filter(self.history_date_label)

        self.clear_history_date_btn = create_button(
            "Clear Date",
            "subtle",
            fixed_height=30,
        )
        self.clear_history_date_btn.clicked.connect(
            self._clear_history_date_filter
        )
        self.clear_history_date_btn.setVisible(False)
        self.history_filter_bar.add_filter(self.clear_history_date_btn)

    def load_data(self):
        try:
            self._appointments = self._collect_appointments()
            self._count_label.setText(
                f"{len(self._appointments)} scheduled appointments"
            )
            self._render_calendar()
            self._render_history()
        except Exception:
            logger.exception("Failed to load calendar data")

    def _collect_appointments(self):
        AppointmentService().backfill_all()

        session = SessionLocal()

        try:
            missionaries = (
                session.query(Appointment, Missionary)
                .join(Missionary, Appointment.missionary_id == Missionary.id)
                .filter(
                    Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
                    Missionary.status == "ACTIVE",
                )
                .all()
            )
            today = date.today()
            appointments = []

            for appointment, missionary in missionaries:
                field_config = next(
                    (
                        item
                        for item in APPOINTMENT_FIELDS
                        if item[0] == appointment.appointment_field
                    ),
                    None,
                )
                if field_config is None:
                    continue

                field, label, color = field_config
                appt_date = appointment.scheduled_date
                if not appt_date:
                    continue
                if getattr(missionary, field, None) != appt_date:
                    continue

                days_offset = (appt_date - today).days
                appointments.append(
                    AppointmentItem(
                        appointment_id=appointment.id,
                        missionary_id=missionary.id,
                        full_name=missionary.full_name or "",
                        current_stage=missionary.current_stage or "",
                        date=appt_date,
                        type=label,
                        color=color,
                        field=field,
                        days_offset=days_offset,
                        bucket=self._appointment_bucket(
                            appt_date,
                            today,
                        ),
                    )
                )

            return sorted(
                appointments,
                key=lambda item: (
                    item.date,
                    item.type,
                    item.full_name.casefold(),
                ),
            )
        finally:
            session.close()

    def _appointment_bucket(self, appt_date, today):
        return appointment_bucket(appt_date, today)

    def _select_tab(self, key):
        if key == TAB_HISTORY:
            self.tab_stack.setCurrentIndex(self.history_index)
        else:
            self.tab_stack.setCurrentIndex(self.calendar_index)
            key = TAB_CALENDAR

        self._selected_tab = key
        if self.tab_control is not None:
            current_key = getattr(self.tab_control, "currentRouteKey", lambda: None)()
            if current_key != key:
                self.tab_control.setCurrentItem(key)
        elif key in self.tab_buttons:
            self.tab_buttons[key].setChecked(True)

    def _render_calendar(self):
        self._clear_layout(self.calendar_layout)
        self._build_summary_cards()

        visible_dates = visible_range_for_mode(
            self._calendar_mode,
            self._anchor_date,
        )
        visible_set = set(visible_dates)
        filtered = self._apply_calendar_filters(self._appointments)
        visible_items = [
            item for item in filtered if item.date in visible_set
        ]

        calendar_stack = QWidget()
        calendar_stack.setObjectName("CalendarStack")
        stack_layout = QVBoxLayout()
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)
        calendar_stack.setLayout(stack_layout)

        overdue_strip = self._build_overdue_strip(filtered, visible_set)
        if overdue_strip is not None:
            stack_layout.addWidget(overdue_strip)

        stack_layout.addWidget(self._build_calendar_toolbar())

        grid_card = create_card()
        grid_card.setObjectName("CalendarGridCard")
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(14, 14, 14, 14)
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(8)
        grid_card.setLayout(grid_layout)

        for column, label in enumerate(WEEKDAY_LABELS):
            header = QLabel(label.upper())
            header.setObjectName("CalendarWeekdayHeader")
            header.setAlignment(Qt.AlignCenter)
            grid_layout.addWidget(header, 0, column)
            grid_layout.setColumnStretch(column, 1)

        day_items = self._appointments_by_date(visible_items)
        today = date.today()
        for index, day in enumerate(visible_dates):
            row = index // 7 + 1
            column = index % 7
            grid_layout.addWidget(
                self._make_day_cell(
                    day,
                    day_items.get(day, []),
                    today,
                    self._calendar_mode,
                ),
                row,
                column,
            )
            grid_layout.setRowStretch(row, 1)

        stack_layout.addWidget(grid_card)

        self.calendar_layout.addWidget(calendar_stack)

        if not self._appointments:
            self.calendar_layout.addWidget(
                self._make_empty_state("No scheduled appointments.")
            )
        elif not visible_items:
            self.calendar_layout.addWidget(
                self._make_empty_state(
                    "No appointments in this calendar range."
                )
            )

        self.calendar_layout.addStretch()

    def _build_summary_cards(self):
        today = date.today()
        week_dates = set(visible_range_for_mode(CALENDAR_MODE_WEEK, today))
        counts = {
            "overdue": 0,
            "today": 0,
            "this_week": 0,
        }

        for item in self._appointments:
            if item.bucket == "overdue":
                counts["overdue"] += 1
            if item.date == today:
                counts["today"] += 1
            if item.date in week_dates:
                counts["this_week"] += 1

        row = QHBoxLayout()
        row.setSpacing(16)

        cards = [
            ("overdue", counts["overdue"], "Overdue"),
            ("today", counts["today"], "Today"),
            ("this_week", counts["this_week"], "This Week"),
            ("total", len(self._appointments), "Total Scheduled"),
        ]

        for key, value, title in cards:
            row.addWidget(
                StatCard(
                    value,
                    title,
                    color=SUMMARY_COLORS[key],
                )
            )

        wrapper = QWidget()
        wrapper.setObjectName("CalendarSummaryRow")
        wrapper.setLayout(row)
        self.calendar_layout.addWidget(wrapper)

    def _build_calendar_toolbar(self):
        toolbar = create_card(object_name="CalendarToolbar")
        toolbar.setObjectName("CalendarToolbar")
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        toolbar.setLayout(layout)

        self._add_mode_control(layout)

        layout.addSpacing(8)

        previous_btn = self._make_nav_arrow_button("LEFT_ARROW", "Previous")
        previous_btn.clicked.connect(self._go_previous_range)
        layout.addWidget(previous_btn)

        today_btn = create_button(
            "Today",
            "secondary",
            fixed_height=30,
        )
        today_btn.clicked.connect(self._go_today)
        layout.addWidget(today_btn)

        next_btn = self._make_nav_arrow_button("RIGHT_ARROW", "Next")
        next_btn.clicked.connect(self._go_next_range)
        layout.addWidget(next_btn)

        self.range_title_label = QLabel(self._calendar_range_title())
        self.range_title_label.setObjectName("CalendarRangeTitle")
        self.range_title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.range_title_label, stretch=1)

        self.calendar_search_edit = create_search_edit("Search calendar")
        self.calendar_search_edit.setText(
            getattr(self, "_calendar_search_text", "")
        )
        self.calendar_search_edit.textChanged.connect(
            self._calendar_search_changed
        )
        layout.addWidget(self.calendar_search_edit, stretch=1)

        self.calendar_type_combo = create_combo_box()
        selected_type = getattr(self, "_calendar_type_filter", "All Types")
        for label in ["All Types", "Interpol", "Biometric", "Pickup"]:
            self.calendar_type_combo.addItem(label, label)
        self._select_combo_value(self.calendar_type_combo, selected_type)
        self.calendar_type_combo.currentIndexChanged.connect(
            lambda _=None: self._calendar_type_changed()
        )
        layout.addWidget(self.calendar_type_combo)

        return toolbar

    def _make_nav_arrow_button(self, icon_name, tooltip):
        icon = fluent_icon(icon_name)
        if FLUENT_AVAILABLE and TransparentToolButton is not None and icon:
            button = TransparentToolButton(icon, self)
            button.setFixedSize(32, 30)
        else:
            fallback = "<" if icon_name == "LEFT_ARROW" else ">"
            button = create_button(fallback, "subtle", fixed_height=30)
            button.setFixedWidth(32)

        button.setToolTip(tooltip)
        return button

    def _add_mode_control(self, layout):
        if FLUENT_AVAILABLE and SegmentedWidget is not None:
            self.mode_control = SegmentedWidget(self)
            self.mode_control.setObjectName("CalendarModeSegment")
            self.mode_control.addItem(CALENDAR_MODE_WEEK, "Week")
            self.mode_control.addItem(CALENDAR_MODE_MONTH, "Month")
            self.mode_control.currentItemChanged.connect(
                self._set_calendar_mode
            )
            self.mode_control.setCurrentItem(self._calendar_mode)
            layout.addWidget(self.mode_control)
            return

        self.mode_control = None
        self.week_mode_btn = QPushButton("Week")
        self.week_mode_btn.setObjectName("CalendarModeButton")
        self.week_mode_btn.setCheckable(True)
        self.week_mode_btn.setChecked(
            self._calendar_mode == CALENDAR_MODE_WEEK
        )
        self.week_mode_btn.clicked.connect(
            lambda checked=False:
            self._set_calendar_mode(CALENDAR_MODE_WEEK)
        )
        layout.addWidget(self.week_mode_btn)

        self.month_mode_btn = QPushButton("Month")
        self.month_mode_btn.setObjectName("CalendarModeButton")
        self.month_mode_btn.setCheckable(True)
        self.month_mode_btn.setChecked(
            self._calendar_mode == CALENDAR_MODE_MONTH
        )
        self.month_mode_btn.clicked.connect(
            lambda checked=False:
            self._set_calendar_mode(CALENDAR_MODE_MONTH)
        )
        layout.addWidget(self.month_mode_btn)

    def _apply_calendar_filters(self, appointments):
        query = getattr(self, "_calendar_search_text", "").strip().casefold()
        type_filter = getattr(self, "_calendar_type_filter", "All Types")

        filtered = []
        for item in appointments:
            if query and query not in item.full_name.casefold():
                continue
            if type_filter != "All Types" and item.type != type_filter:
                continue
            filtered.append(item)
        return filtered

    def _build_overdue_strip(self, appointments, visible_set):
        overdue = [
            item
            for item in appointments
            if item.bucket == "overdue" and item.date not in visible_set
        ]
        if not overdue:
            return None

        strip = QFrame()
        strip.setObjectName("CalendarOverdueStrip")
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)
        strip.setLayout(layout)

        label = QLabel(f"{len(overdue)} overdue outside this view")
        label.setObjectName("DangerText")
        layout.addWidget(label)

        for appointment in overdue[:3]:
            chip = self._make_calendar_chip(appointment, compact=True)
            layout.addWidget(chip)

        if len(overdue) > 3:
            more = create_button(
                f"+{len(overdue) - 3} more",
                "subtle",
                fixed_height=26,
            )
            more.setObjectName("CalendarOverflowButton")
            more.clicked.connect(self._show_overdue_history)
            layout.addWidget(more)

        layout.addStretch()
        return strip

    def _make_day_cell(self, day, appointments, today, mode):
        cell = QFrame()
        cell.setObjectName("CalendarDayCell")
        cell.setProperty(
            "outsideMonth",
            mode == CALENDAR_MODE_MONTH
            and day.month != self._anchor_date.month,
        )
        cell.setProperty("today", day == today)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        cell.setLayout(layout)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        day_label = QLabel(str(day.day))
        day_label.setObjectName("CalendarDayNumber")
        if day == today:
            day_label.setProperty("today", True)
        header.addWidget(day_label)

        if appointments:
            count_label = QLabel(str(len(appointments)))
            count_label.setObjectName("CalendarDayCount")
            header.addWidget(count_label)

        header.addStretch()
        layout.addLayout(header)

        max_visible = 4 if mode == CALENDAR_MODE_WEEK else 3
        for appointment in appointments[:max_visible]:
            layout.addWidget(self._make_calendar_chip(appointment))

        if len(appointments) > max_visible:
            overflow = create_button(
                f"+{len(appointments) - max_visible} more",
                "subtle",
                fixed_height=24,
            )
            overflow.setObjectName("CalendarOverflowButton")
            overflow.clicked.connect(
                lambda checked=False, filter_date=day:
                self._show_history_for_date(filter_date)
            )
            layout.addWidget(overflow)

        layout.addStretch()
        return cell

    def _make_calendar_chip(self, appointment, compact=False):
        text = self._calendar_chip_text(appointment, compact)
        chip = QFrame()
        chip.setObjectName("CalendarAppointmentChip")
        chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        chip.setLayout(layout)

        bar = QFrame()
        bar.setObjectName("CalendarAppointmentChipAccent")
        bar.setFixedWidth(4)
        palette = bar.palette()
        palette.setColor(QPalette.Window, QColor(appointment.color))
        bar.setPalette(palette)
        bar.setAutoFillBackground(True)
        layout.addWidget(bar)

        button = create_button(text, "subtle", fixed_height=26)
        button.setObjectName("CalendarAppointmentChipButton")
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setToolTip(
            f"{appointment.type} appointment for {appointment.full_name}"
        )
        button.clicked.connect(
            lambda checked=False, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        layout.addWidget(button, stretch=1)
        return chip

    def _calendar_chip_text(self, appointment, compact=False):
        limit = 28 if compact else 24
        name = appointment.full_name
        if len(name) > limit:
            name = f"{name[:limit - 3]}..."

        separator = ":" if compact else "-"
        return f"{appointment.type} {separator} {name}"

    def _appointments_by_date(self, appointments):
        grouped = {}
        for item in appointments:
            grouped.setdefault(item.date, []).append(item)

        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    item.type,
                    item.full_name.casefold(),
                )
            )
        return grouped

    def _calendar_range_title(self):
        visible_dates = visible_range_for_mode(
            self._calendar_mode,
            self._anchor_date,
        )
        start = visible_dates[0]
        end = visible_dates[-1]

        if self._calendar_mode == CALENDAR_MODE_MONTH:
            return self._anchor_date.strftime("%B %Y")

        if start.month == end.month:
            return f"{start.strftime('%B')} {start.day}-{end.day}, {end.year}"
        return (
            f"{start.strftime('%b')} {start.day} - "
            f"{end.strftime('%b')} {end.day}, {end.year}"
        )

    def _set_calendar_mode(self, mode):
        if mode == self._calendar_mode:
            return

        self._calendar_mode = mode
        self._render_calendar()

    def _go_previous_range(self):
        if self._calendar_mode == CALENDAR_MODE_MONTH:
            self._anchor_date = add_months(self._anchor_date, -1)
        else:
            self._anchor_date = self._anchor_date - timedelta(days=7)
        self._render_calendar()

    def _go_next_range(self):
        if self._calendar_mode == CALENDAR_MODE_MONTH:
            self._anchor_date = add_months(self._anchor_date, 1)
        else:
            self._anchor_date = self._anchor_date + timedelta(days=7)
        self._render_calendar()

    def _go_today(self):
        self._anchor_date = date.today()
        self._render_calendar()

    def _calendar_type_changed(self):
        self._calendar_type_filter = (
            self.calendar_type_combo.currentData() or "All Types"
        )
        self._render_calendar()

    def _calendar_search_changed(self, text):
        self._calendar_search_text = text
        self._render_calendar()

    def _render_history(self):
        if not hasattr(self, "history_layout"):
            return

        self._clear_layout(self.history_layout)
        self._sync_history_date_filter_ui()

        filtered = self._apply_history_filters(self._appointments)
        if not self._appointments:
            self.history_layout.addWidget(
                self._make_empty_state("No scheduled appointments.")
            )
            self.history_layout.addStretch()
            return

        if not filtered:
            self.history_layout.addWidget(
                self._make_empty_state(
                    "No appointments match the current filters."
                )
            )
            self.history_layout.addStretch()
            return

        unique_missionaries = {item.missionary_id for item in filtered}
        if len(unique_missionaries) == 1:
            self.history_layout.addWidget(
                self._make_history_list_card(filtered)
            )
        else:
            self._build_history_sections(
                filtered,
                self.history_sort_combo.currentData() or "asc",
            )
        self.history_layout.addStretch()

    def _apply_history_filters(self, appointments):
        query = self.history_search_edit.text().strip().casefold()
        type_filter = self.history_type_combo.currentData() or "All Types"
        status_filter = self.history_status_combo.currentData() or "all"
        sort_direction = self.history_sort_combo.currentData() or "asc"

        filtered = []
        for item in appointments:
            if self._history_exact_date and item.date != self._history_exact_date:
                continue
            if query and query not in item.full_name.casefold():
                continue
            if type_filter != "All Types" and item.type != type_filter:
                continue
            if not self._matches_status_filter(item, status_filter):
                continue
            filtered.append(item)

        reverse = sort_direction == "desc"
        return sorted(
            filtered,
            key=lambda item: (
                item.date,
                item.type,
                item.full_name.casefold(),
            ),
            reverse=reverse,
        )

    def _matches_status_filter(self, item, status_filter):
        if status_filter == "all":
            return True
        if status_filter == "needs_attention":
            return item.bucket in {"overdue", "today"}
        if status_filter == "upcoming":
            return item.days_offset > 0
        return item.bucket == status_filter

    def _build_history_sections(self, appointments, sort_direction="asc"):
        bucket_order = (
            list(reversed(BUCKET_ORDER))
            if sort_direction == "desc"
            else BUCKET_ORDER
        )

        for bucket in bucket_order:
            bucket_items = [
                item for item in appointments if item.bucket == bucket
            ]
            if not bucket_items:
                continue

            self.history_layout.addWidget(
                self._make_section_header(bucket, len(bucket_items))
            )

            for appt_date, day_items in groupby(
                bucket_items,
                key=lambda item: item.date,
            ):
                self.history_layout.addWidget(
                    self._make_day_card(appt_date, list(day_items))
                )

    def _make_history_list_card(self, appointments):
        card = create_header_card(
            appointments[0].full_name,
            object_name="CalendarHistoryFocusCard",
        )
        card.setObjectName("CalendarHistoryFocusCard")

        header = card.headerLayout
        header.addStretch()
        header.addWidget(
            create_info_badge(
                f"{len(appointments)} appointment"
                f"{'s' if len(appointments) != 1 else ''}",
                level=BUCKET_INFO_LEVELS[appointments[0].bucket],
            )
        )

        body_layout = card.viewLayout
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        content = QWidget()
        content.setObjectName("CalendarHistoryFocusList")
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        content.setLayout(list_layout)
        body_layout.addWidget(content)

        subtitle = BodyLabel(
            appointments[0].current_stage or "No current stage"
        )
        subtitle.setObjectName("CalendarHistoryFocusMeta")
        subtitle.setContentsMargins(18, 0, 18, 10)
        list_layout.addWidget(subtitle)

        for index, appointment in enumerate(appointments):
            list_layout.addWidget(
                self._make_history_list_row(
                    appointment,
                    alternate=index % 2 == 1,
                )
            )

        return card

    def _make_history_list_row(self, appointment, alternate=False):
        row = QFrame()
        row.setObjectName(
            "CalendarHistoryFocusRowAlt"
            if alternate
            else "CalendarHistoryFocusRow"
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)
        row.setLayout(layout)

        left_stack = QVBoxLayout()
        left_stack.setContentsMargins(0, 0, 0, 0)
        left_stack.setSpacing(4)

        top_line = QHBoxLayout()
        top_line.setContentsMargins(0, 0, 0, 0)
        top_line.setSpacing(10)

        type_badge = QLabel(appointment.type)
        type_badge.setObjectName("CalendarTypeBadge")
        type_badge.setStyleSheet(
            "QLabel#CalendarTypeBadge {"
            f"background-color: {appointment.color};"
            "color: white;"
            "border-radius: 999px;"
            "padding: 3px 10px;"
            "font-size: 11px;"
            "font-weight: 700;"
            "}"
        )
        type_badge.setAlignment(Qt.AlignCenter)
        top_line.addWidget(type_badge)

        top_line.addWidget(
            StrongBodyLabel(appointment.date.strftime("%A, %B %d, %Y"))
        )
        top_line.addStretch()
        top_line.addWidget(
            create_info_badge(
                appointment_distance_text(appointment.days_offset),
                level=BUCKET_INFO_LEVELS[appointment.bucket],
            )
        )

        top_wrapper = QWidget()
        top_wrapper.setLayout(top_line)
        left_stack.addWidget(top_wrapper)

        left_stack.addWidget(
            BodyLabel(
                f"Stage: {appointment.current_stage or 'No current stage'}"
            )
        )

        left_wrapper = QWidget()
        left_wrapper.setLayout(left_stack)
        layout.addWidget(left_wrapper, stretch=1)

        view_btn = create_pill_button("View")
        view_btn.setFixedHeight(28)
        view_btn.clicked.connect(
            lambda _=None, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        complete_btn = create_pill_button("Complete")
        complete_btn.setObjectName("CalendarCompleteAppointmentButton")
        complete_btn.setFixedHeight(28)
        complete_btn.clicked.connect(
            lambda _=None, appt=appointment:
            self._complete_appointment(appt)
        )
        missed_btn = create_pill_button("Missed")
        missed_btn.setObjectName("CalendarMissedAppointmentButton")
        missed_btn.setFixedHeight(28)
        missed_btn.clicked.connect(
            lambda _=None, appt=appointment:
            self._miss_appointment(appt)
        )
        layout.addWidget(complete_btn)
        layout.addWidget(missed_btn)
        layout.addWidget(view_btn)

        return row

    def _make_section_header(self, bucket, count):
        row = QFrame()
        row.setObjectName("CalendarSectionHeader")
        row.setProperty("tone", BUCKET_TONES[bucket])

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 2)
        layout.setSpacing(8)
        row.setLayout(layout)

        title = QLabel(BUCKET_LABELS[bucket].upper())
        title.setObjectName("CalendarSectionTitle")
        title.setProperty("tone", BUCKET_TONES[bucket])
        layout.addWidget(title)

        count_label = QLabel(str(count))
        count_label.setObjectName("CalendarSectionCount")
        count_label.setProperty("tone", BUCKET_TONES[bucket])
        layout.addWidget(count_label)

        layout.addStretch()
        return row

    def _make_day_card(self, appt_date, appointments):
        card = create_card()
        card.setObjectName("CalendarDayCard")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        card.setLayout(layout)

        header = QFrame()
        header.setObjectName("CalendarDayHeader")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(18, 14, 18, 12)
        header_layout.setSpacing(10)
        header.setLayout(header_layout)

        date_label = QLabel(appt_date.strftime("%A, %B %d, %Y"))
        date_label.setObjectName("PanelTitle")
        header_layout.addWidget(date_label)

        header_layout.addStretch()

        distance = appointment_distance_text(appointments[0].days_offset)
        distance_label = QLabel(distance)
        distance_label.setObjectName("AlertBadge")
        distance_label.setProperty(
            "tone",
            BUCKET_TONES[appointments[0].bucket],
        )
        header_layout.addWidget(distance_label)
        layout.addWidget(header)

        for index, appointment in enumerate(appointments):
            layout.addWidget(
                self._make_appointment_row(
                    appointment,
                    alternate=index % 2 == 1,
                )
            )

        return card

    def _make_appointment_row(self, appointment, alternate=False):
        row = QFrame()
        row.setObjectName(
            "CalendarAppointmentRowAlt"
            if alternate
            else "CalendarAppointmentRow"
        )
        row.setProperty("tone", BUCKET_TONES[appointment.bucket])

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 11, 18, 11)
        layout.setSpacing(12)
        row.setLayout(layout)

        bar = QFrame()
        bar.setObjectName("CalendarTypeBar")
        bar.setFixedWidth(4)
        bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        palette = bar.palette()
        palette.setColor(QPalette.Window, QColor(appointment.color))
        bar.setPalette(palette)
        bar.setAutoFillBackground(True)
        layout.addWidget(bar)

        type_badge = QLabel(appointment.type)
        type_badge.setObjectName("CalendarTypeBadge")
        type_badge.setStyleSheet(
            "QLabel#CalendarTypeBadge {"
            f"background-color: {appointment.color};"
            "color: white;"
            "border-radius: 10px;"
            "padding: 3px 10px;"
            "font-size: 11px;"
            "font-weight: 700;"
            "}"
        )
        type_badge.setFixedWidth(86)
        type_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(type_badge)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        name_label = QLabel(appointment.full_name)
        name_label.setObjectName("StrongText")
        text_stack.addWidget(name_label)

        meta = appointment.current_stage or "No current stage"
        meta_label = QLabel(f"Stage: {meta}")
        meta_label.setObjectName("MiniMutedText")
        text_stack.addWidget(meta_label)
        layout.addLayout(text_stack, stretch=1)

        due_label = QLabel(
            appointment_distance_text(appointment.days_offset)
        )
        due_label.setObjectName("CalendarDueText")
        due_label.setProperty("tone", BUCKET_TONES[appointment.bucket])
        due_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        due_label.setMinimumWidth(110)
        layout.addWidget(due_label)

        view_btn = create_button("View", "subtle", fixed_height=28)
        view_btn.clicked.connect(
            lambda _=None, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        complete_btn = create_button("Complete", "success", fixed_height=28)
        complete_btn.setObjectName("CalendarCompleteAppointmentButton")
        complete_btn.clicked.connect(
            lambda _=None, appt=appointment:
            self._complete_appointment(appt)
        )
        missed_btn = create_button("Missed", "danger", fixed_height=28)
        missed_btn.setObjectName("CalendarMissedAppointmentButton")
        missed_btn.clicked.connect(
            lambda _=None, appt=appointment:
            self._miss_appointment(appt)
        )
        layout.addWidget(complete_btn)
        layout.addWidget(missed_btn)
        layout.addWidget(view_btn)

        return row

    def _complete_appointment(self, appointment):
        if not appointment.appointment_id:
            return

        try:
            AppointmentService().complete_appointment(
                appointment.appointment_id
            )
            show_message(
                self,
                "Appointment Completed",
                f"{appointment.type} appointment marked complete.",
            )
            self.load_data()
        except Exception:
            logger.exception("Failed to complete appointment")
            show_message(
                self,
                "Appointment Error",
                "Could not mark the appointment complete.",
                kind="critical",
            )

    def _miss_appointment(self, appointment):
        if not appointment.appointment_id:
            return

        confirm = show_message(
            self,
            "Mark Appointment Missed?",
            (
                f"This will mark the {appointment.type} appointment as missed, "
                "hide it from overdue, and create a follow-up task for the new "
                "pago/cita."
            ),
            kind="question",
            buttons="yes_no",
        )
        if confirm not in {1, 16384}:
            return

        try:
            AppointmentService().miss_appointment(
                appointment.appointment_id
            )
            show_message(
                self,
                "Appointment Missed",
                (
                    f"{appointment.type} appointment marked missed. "
                    "A follow-up task was created."
                ),
            )
            self.load_data()
        except Exception:
            logger.exception("Failed to mark appointment missed")
            show_message(
                self,
                "Appointment Error",
                "Could not mark the appointment missed.",
                kind="critical",
            )

    def _show_history_for_date(self, filter_date):
        self._history_exact_date = filter_date
        self.history_search_edit.clear()
        self._select_combo_value(self.history_status_combo, "all")
        calendar_type = getattr(self, "_calendar_type_filter", "All Types")
        self._select_combo_value(self.history_type_combo, calendar_type)
        self._render_history()
        self._select_tab(TAB_HISTORY)

    def _show_overdue_history(self):
        self._history_exact_date = None
        self.history_search_edit.clear()
        self._select_combo_value(self.history_status_combo, "overdue")
        self._render_history()
        self._select_tab(TAB_HISTORY)

    def _clear_history_date_filter(self):
        self._history_exact_date = None
        self._render_history()

    def _sync_history_date_filter_ui(self):
        has_date = self._history_exact_date is not None
        if has_date:
            self.history_date_label.setText(
                self._history_exact_date.strftime("%b %d, %Y")
            )
        else:
            self.history_date_label.setText("")

        self.history_date_label.setVisible(has_date)
        self.clear_history_date_btn.setVisible(has_date)

    def _make_empty_state(self, message):
        card = create_card()
        card.setObjectName("CalendarEmptyState")

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 30, 24, 30)
        layout.setSpacing(6)
        card.setLayout(layout)

        title = QLabel(message)
        title.setObjectName("PanelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        detail = QLabel("Adjust the filters or add appointment dates.")
        detail.setObjectName("MutedText")
        detail.setAlignment(Qt.AlignCenter)
        layout.addWidget(detail)

        return card

    def _select_combo_value(self, combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            widget = item.widget()

            if child_layout is not None:
                self._clear_layout(child_layout)
            if widget is not None:
                widget.deleteLater()

    def _open_missionary(self, missionary_id):
        try:
            detail = self.main_window.detail_page

            session = SessionLocal()

            try:
                missionary = (
                    session.query(Missionary)
                    .filter_by(id=missionary_id)
                    .first()
                )

                if missionary:
                    detail.load_missionary(missionary)
                    self.main_window.stack.setCurrentIndex(2)
                    self.main_window.sidebar.setCurrentRow(1)

            finally:
                session.close()

        except Exception:
            logger.exception("Failed to open missionary detail")
