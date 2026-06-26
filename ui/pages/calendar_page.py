from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QDrag, QPalette, QPixmap
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
    from qfluentwidgets import TransparentToolButton
except Exception:
    TransparentToolButton = None

from database.models.appointment import (
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
)
from services.appointment_service import AppointmentService
from services.secretary_work_service import SecretaryWorkService
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    BodyLabel,
    DialogFooter,
    FLUENT_AVAILABLE,
    InfoLevel,
    FilterBar,
    MaskDialogBase,
    PageHeader,
    StatCard,
    StrongBodyLabel,
    SubtitleLabel,
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
    setup_dialog_shell,
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
TASK_DRAG_MIME = "application/x-mission-task-id"
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
    appointment_uid: str = ""
    status: str = APPOINTMENT_STATUS_SCHEDULED
    marked_at: object = None
    status_reason: str = ""
    appointment_id: int = 0


class CalendarDaySummaryDialog(MaskDialogBase):
    def __init__(self, calendar_page, summary_date, appointments, tasks):
        super().__init__(calendar_page)
        self.calendar_page = calendar_page
        self.summary_date = summary_date
        self.appointments = list(appointments)
        self.tasks = list(tasks)

        self.setWindowTitle(summary_date.strftime("%B %d, %Y"))
        self.setModal(True)
        self.surface = setup_dialog_shell(
            self,
            surface_width=720,
            surface_min_height=420,
            use_masked_shell=True,
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface.setLayout(layout)

        header = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(24, 22, 24, 14)
        header_layout.setSpacing(6)
        header.setLayout(header_layout)

        title = SubtitleLabel(
            self.summary_date.strftime("%A, %B %d, %Y")
        )
        header_layout.addWidget(title)

        subtitle = BodyLabel("Appointments and tasks planned for this day.")
        subtitle.setObjectName("MutedText")
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("CalendarDaySummaryScroll")
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        appointments_title = QLabel("Appointments")
        appointments_title.setObjectName("PanelTitle")
        body_layout.addWidget(appointments_title)

        if self.appointments:
            for index, appointment in enumerate(self.appointments):
                body_layout.addWidget(
                    self.calendar_page._make_appointment_row(
                        appointment,
                        alternate=index % 2 == 1,
                    )
                )
        else:
            empty = QLabel("No appointments")
            empty.setObjectName("CalendarNoAppointmentsLabel")
            body_layout.addWidget(empty)

        tasks_title = QLabel("Tasks")
        tasks_title.setObjectName("PanelTitle")
        body_layout.addWidget(tasks_title)

        if self.tasks:
            for index, task in enumerate(self.tasks):
                body_layout.addWidget(
                    self.calendar_page._make_task_row(
                        task,
                        alternate=index % 2 == 1,
                    )
                )
        else:
            empty = QLabel("No tasks planned.")
            empty.setObjectName("MutedText")
            body_layout.addWidget(empty)

        footer = DialogFooter()
        close_btn = create_button("Close", "secondary")
        close_btn.clicked.connect(self.reject)
        footer.add_action(close_btn)

        add_task_btn = create_button("Add Task", "primary")
        add_task_btn.setObjectName("CalendarDayAddTaskButton")
        add_task_btn.clicked.connect(self._add_task)
        footer.add_action(add_task_btn)
        layout.addWidget(footer)

    def _add_task(self):
        if self.calendar_page._add_task(default_work_date=self.summary_date):
            self.accept()


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


def appointment_status_text(appointment):
    if appointment.status == APPOINTMENT_STATUS_COMPLETED:
        return "Completed"
    if appointment.status == APPOINTMENT_STATUS_MISSED:
        return "Missed"
    return appointment_distance_text(appointment.days_offset)


def appointment_tone(appointment):
    if appointment.status == APPOINTMENT_STATUS_COMPLETED:
        return "success"
    if appointment.status == APPOINTMENT_STATUS_MISSED:
        return "danger"
    return BUCKET_TONES[appointment.bucket]


def appointment_info_level(appointment):
    if appointment.status == APPOINTMENT_STATUS_COMPLETED:
        return InfoLevel.SUCCESS
    if appointment.status == APPOINTMENT_STATUS_MISSED:
        return InfoLevel.ERROR
    return BUCKET_INFO_LEVELS[appointment.bucket]


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
    return month_grid_dates(anchor_date.year, anchor_date.month)


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
TASK_DRAG_MIME = "application/x-mission-task-id"
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
    return month_grid_dates(anchor_date.year, anchor_date.month)


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
        self._history_appointments = []
        self._tasks = []
        self._calendar_mode = CALENDAR_MODE_MONTH
        self._anchor_date = date.today()
        self._calendar_detail_date = None
        self._show_overdue_detail = False
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
            ("Completed", APPOINTMENT_STATUS_COMPLETED),
            ("Missed", APPOINTMENT_STATUS_MISSED),
        ]:
            self.history_status_combo.addItem(label, value)
        self.history_status_combo.currentIndexChanged.connect(
            lambda _=None: self._render_history()
        )
        self.history_filter_bar.add_filter(self.history_status_combo)

        self.history_sort_combo = create_combo_box()
        for label, value in [
            ("Date Descending", "desc"),
            ("Date Ascending", "asc"),
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
            self._history_appointments = self._collect_history_appointments()
            self._tasks = self._collect_tasks()
            self._count_label.setText(
                f"{len(self._appointments)} scheduled appointments"
            )
            self._render_calendar()
            self._render_history()
        except Exception:
            logger.exception("Failed to load calendar data")

    def _collect_appointments(self):
        return self._appointment_items_from_snapshots(
            AppointmentService().list_scheduled_appointments()
        )

    def _collect_history_appointments(self):
        return self._appointment_items_from_snapshots(
            AppointmentService().list_history_appointments(),
            newest_first=True,
        )

    def _collect_tasks(self):
        return SecretaryWorkService().list_calendar_tasks()

    def _appointment_items_from_snapshots(self, snapshots, newest_first=False):
        today = date.today()
        appointments = []
        for snapshot in snapshots:
            field_config = next(
                (
                    item
                    for item in APPOINTMENT_FIELDS
                    if item[0] == snapshot["appointment_field"]
                ),
                None,
            )
            if field_config is None:
                continue

            field, label, color = field_config
            appt_date = snapshot["scheduled_date"]
            if not appt_date:
                continue

            days_offset = (appt_date - today).days
            appointments.append(
                AppointmentItem(
                    appointment_uid=snapshot.get("appointment_uid", ""),
                    appointment_id=snapshot["id"],
                    missionary_id=snapshot["missionary_id"],
                    full_name=snapshot.get("full_name", ""),
                    current_stage=snapshot.get("current_stage", ""),
                    date=appt_date,
                    type=label,
                    color=color,
                    field=field,
                    days_offset=days_offset,
                    bucket=self._appointment_bucket(appt_date, today),
                    status=snapshot.get("status", APPOINTMENT_STATUS_SCHEDULED),
                    marked_at=snapshot.get("marked_at"),
                    status_reason=snapshot.get("status_reason", ""),
                )
            )

        return sorted(
            appointments,
            key=lambda item: (
                item.date,
                item.type,
                item.full_name.casefold(),
            ),
            reverse=newest_first,
        )

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
        visible_tasks = [
            task
            for task in self._tasks
            if task.get("work_date") in visible_set
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
        task_items = self._tasks_by_date(self._tasks)
        today = date.today()
        for index, day in enumerate(visible_dates):
            row = index // 7 + 1
            column = index % 7
            grid_layout.addWidget(
                self._make_day_cell(
                    day,
                    day_items.get(day, []),
                    task_items.get(day, []),
                    today,
                    self._calendar_mode,
                ),
                row,
                column,
            )
            grid_layout.setRowStretch(row, 1)

        stack_layout.addWidget(grid_card)

        if self._show_overdue_detail:
            overdue_items = [
                item for item in filtered if item.bucket == "overdue"
            ]
            if overdue_items:
                stack_layout.addWidget(self._make_overdue_detail_card(overdue_items))
        self.calendar_layout.addWidget(calendar_stack)

        if not self._appointments and not self._tasks:
            self.calendar_layout.addWidget(
                self._make_empty_state("No scheduled appointments.")
            )
        elif not visible_items and not visible_tasks:
            self.calendar_layout.addWidget(
                self._make_empty_state(
                    "No appointments or tasks in this calendar range."
                )
            )

        self.calendar_layout.addStretch()

    def _build_summary_cards(self):
        today = date.today()
        week_start = week_start_for(today)
        week_dates = {
            week_start + timedelta(days=offset)
            for offset in range(7)
        }
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

        add_task_btn = create_button(
            "Add Task",
            "primary",
            fixed_height=30,
        )
        add_task_btn.setObjectName("CalendarAddTaskButton")
        add_task_btn.clicked.connect(
            lambda checked=False: self._add_task()
        )
        layout.addWidget(add_task_btn)

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
            more.clicked.connect(self._show_overdue_calendar_details)
            layout.addWidget(more)

        layout.addStretch()
        return strip

    def _make_day_cell(self, day, appointments, tasks, today, mode):
        cell = QFrame()
        cell.setObjectName("CalendarDayCell")
        cell.setProperty(
            "outsideMonth",
            mode == CALENDAR_MODE_MONTH
            and day.month != self._anchor_date.month,
        )
        cell.setProperty("today", day == today)
        cell.mousePressEvent = (
            lambda event, filter_date=day:
            self._show_calendar_day_details(filter_date)
        )
        cell.setAcceptDrops(True)
        cell.dragEnterEvent = (
            lambda event:
            self._task_drag_enter_event(event)
        )
        cell.dropEvent = (
            lambda event, target_day=day:
            self._task_drop_event(event, target_day)
        )

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

        total_items = len(appointments) + len(tasks)
        if total_items:
            count_label = QLabel(str(total_items))
            count_label.setObjectName("CalendarDayCount")
            header.addWidget(count_label)

        header.addStretch()
        layout.addLayout(header)

        max_visible = 3
        visible_count = 0
        for appointment in appointments[:max_visible]:
            layout.addWidget(self._make_calendar_chip(appointment))
            visible_count += 1

        remaining_slots = max(0, max_visible - visible_count)
        for task in tasks[:remaining_slots]:
            layout.addWidget(self._make_task_chip(task))
            visible_count += 1

        if total_items > max_visible:
            overflow = create_button(
                f"+{total_items - max_visible} more",
                "subtle",
                fixed_height=24,
            )
            overflow.setObjectName("CalendarOverflowButton")
            overflow.clicked.connect(
                lambda checked=False, filter_date=day:
                self._show_calendar_day_details(filter_date)
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

    def _enable_task_drag(self, widget, task_id, preview_widget=None):
        if task_id is None:
            return

        preview_widget = preview_widget or widget
        original_press = widget.mousePressEvent
        original_move = widget.mouseMoveEvent

        def mouse_press(event):
            if event.button() == Qt.LeftButton:
                widget._task_drag_start_pos = event.position().toPoint()
            original_press(event)

        def mouse_move(event):
            start_pos = getattr(widget, "_task_drag_start_pos", None)
            if (
                start_pos is not None
                and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - start_pos).manhattanLength()
                >= 8
            ):
                mime = QMimeData()
                mime.setData(TASK_DRAG_MIME, str(task_id).encode("utf-8"))
                drag = QDrag(widget)
                drag.setMimeData(mime)
                pixmap = QPixmap(preview_widget.size())
                pixmap.fill(Qt.transparent)
                preview_widget.render(pixmap)
                drag.setPixmap(pixmap)
                drag.setHotSpot(
                    widget.mapTo(
                        preview_widget,
                        event.position().toPoint(),
                    )
                )
                drag.exec(Qt.MoveAction)
                return
            original_move(event)

        widget.mousePressEvent = mouse_press
        widget.mouseMoveEvent = mouse_move

    def _task_drag_enter_event(self, event):
        if event.mimeData().hasFormat(TASK_DRAG_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _task_drop_event(self, event, target_day):
        if not event.mimeData().hasFormat(TASK_DRAG_MIME):
            event.ignore()
            return

        try:
            task_id = int(bytes(event.mimeData().data(TASK_DRAG_MIME)).decode("utf-8"))
            SecretaryWorkService().update_task(task_id, work_date=target_day)
            event.acceptProposedAction()
            self.load_data()
            self._refresh_office_work_page()
        except Exception:
            logger.exception("Failed to move calendar task")
            event.ignore()
            show_message(
                self,
                "Calendar Task",
                "Could not move that task.",
                kind="warning",
            )

    def _make_task_chip(self, task):
        title = task.get("title", "")
        text = self._task_chip_text(task)
        chip = QFrame()
        chip.setObjectName("CalendarTaskChip")
        chip.setProperty("done", task.get("status") == "DONE")
        chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        chip.setLayout(layout)

        bar = QFrame()
        bar.setObjectName("CalendarAppointmentChipAccent")
        bar.setFixedWidth(4)
        palette = bar.palette()
        task_color = "#7C3AED" if task.get("is_group_task") else "#2563EB"
        palette.setColor(QPalette.Window, QColor(task_color))
        bar.setPalette(palette)
        bar.setAutoFillBackground(True)
        layout.addWidget(bar)

        button = create_button(text, "subtle", fixed_height=26)
        button.setObjectName("CalendarTaskChipButton")
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scope = task.get("scope_label") or task.get("missionary_name") or ""
        tooltip = f"Task: {title}"
        if task.get("due_date"):
            tooltip = f"{tooltip} - due {task['due_date'].strftime('%b %d, %Y')}"
        if scope:
            tooltip = f"{tooltip} - {scope}"
        button.setToolTip(tooltip)
        button.clicked.connect(
            lambda checked=False, task_data=task:
            self._edit_task(task_data)
        )
        self._enable_task_drag(chip, task.get("id"), chip)
        self._enable_task_drag(button, task.get("id"), chip)
        layout.addWidget(button, stretch=1)

        if task.get("status") != "DONE":
            done_btn = create_button("Done", "success", fixed_height=28)
            done_btn.setObjectName("CalendarTaskDoneButton")
            done_btn.setMinimumWidth(72)
            done_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            done_btn.clicked.connect(
                lambda checked=False, task_id=task.get("id"):
                self._complete_task(task_id)
            )
            layout.addWidget(done_btn)
        return chip

    def _calendar_chip_text(self, appointment, compact=False):
        limit = 28 if compact else 24
        name = appointment.full_name
        if len(name) > limit:
            name = f"{name[:limit - 3]}..."

        separator = ":" if compact else "-"
        return f"{appointment.type} {separator} {name}"

    def _task_chip_text(self, task):
        title = task.get("title", "")
        limit = 24
        if len(title) > limit:
            title = f"{title[:limit - 3]}..."
        return f"Task - {title}"

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

    def _tasks_by_date(self, tasks):
        grouped = {}
        for task in tasks:
            work_date = task.get("work_date")
            if work_date is not None:
                grouped.setdefault(work_date, []).append(task)

        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    item.get("status") == "DONE",
                    item.get("priority", ""),
                    item.get("title", "").casefold(),
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

        return self._anchor_date.strftime("%B %Y")

    def _set_calendar_mode(self, mode):
        if mode == self._calendar_mode:
            return

        self._calendar_mode = mode
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._render_calendar()

    def _go_previous_range(self):
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._anchor_date = add_months(self._anchor_date, -1)
        self._render_calendar()

    def _go_next_range(self):
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._anchor_date = add_months(self._anchor_date, 1)
        self._render_calendar()

    def _go_today(self):
        self._anchor_date = date.today()
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._render_calendar()

    def _calendar_type_changed(self):
        self._calendar_type_filter = (
            self.calendar_type_combo.currentData() or "All Types"
        )
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._render_calendar()

    def _calendar_search_changed(self, text):
        self._calendar_search_text = text
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._render_calendar()

    def _show_calendar_day_details(self, filter_date):
        self._show_overdue_detail = False
        appointments = [
            item
            for item in self._apply_calendar_filters(self._appointments)
            if item.date == filter_date
        ]
        tasks = self._tasks_by_date(self._tasks).get(filter_date, [])
        dialog = CalendarDaySummaryDialog(
            self,
            filter_date,
            appointments,
            tasks,
        )
        dialog.exec()

    def _show_overdue_calendar_details(self):
        self._calendar_detail_date = None
        self._show_overdue_detail = True
        self._render_calendar()

    def _render_history(self):
        if not hasattr(self, "history_layout"):
            return

        self._clear_layout(self.history_layout)
        self._sync_history_date_filter_ui()

        filtered = self._apply_history_filters(self._history_appointments)
        if not self._history_appointments:
            self.history_layout.addWidget(
                self._make_empty_state("No appointment history yet.")
            )
            self.history_layout.addStretch()
            return

        if not filtered:
            self.history_layout.addWidget(
                self._make_empty_state(
                    "No historical appointments match the current filters."
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
        return item.status == status_filter

    def _build_history_sections(self, appointments, sort_direction="asc"):
        _ = sort_direction
        status_order = [
            APPOINTMENT_STATUS_COMPLETED,
            APPOINTMENT_STATUS_MISSED,
        ]

        for status in status_order:
            status_items = [
                item for item in appointments if item.status == status
            ]
            if not status_items:
                continue

            self.history_layout.addWidget(
                self._make_history_status_header(status, len(status_items))
            )

            for appt_date, day_items in groupby(
                status_items,
                key=lambda item: item.date,
            ):
                self.history_layout.addWidget(
                    self._make_day_card(appt_date, list(day_items))
                )

    def _make_history_status_header(self, status, count):
        tone = "success" if status == APPOINTMENT_STATUS_COMPLETED else "danger"
        title_text = "Completed" if status == APPOINTMENT_STATUS_COMPLETED else "Missed"

        row = QFrame()
        row.setObjectName("CalendarSectionHeader")
        row.setProperty("tone", tone)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 2)
        layout.setSpacing(8)
        row.setLayout(layout)

        title = QLabel(title_text.upper())
        title.setObjectName("CalendarSectionTitle")
        title.setProperty("tone", tone)
        layout.addWidget(title)

        count_label = QLabel(str(count))
        count_label.setObjectName("CalendarSectionCount")
        count_label.setProperty("tone", tone)
        layout.addWidget(count_label)

        layout.addStretch()
        return row

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
                level=appointment_info_level(appointments[0]),
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
                appointment_status_text(appointment),
                level=appointment_info_level(appointment),
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
        if appointment.status == APPOINTMENT_STATUS_SCHEDULED:
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

        distance = appointment_status_text(appointments[0])
        distance_label = QLabel(distance)
        distance_label.setObjectName("AlertBadge")
        distance_label.setProperty(
            "tone",
            appointment_tone(appointments[0]),
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

    def _make_overdue_detail_card(self, appointments):
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

        title = QLabel("Overdue scheduled appointments")
        title.setObjectName("PanelTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        badge = QLabel(f"{len(appointments)} need action")
        badge.setObjectName("AlertBadge")
        badge.setProperty("tone", "danger")
        header_layout.addWidget(badge)
        layout.addWidget(header)

        ordered = sorted(
            appointments,
            key=lambda item: (
                item.date,
                item.type,
                item.full_name.casefold(),
            ),
        )
        for index, appointment in enumerate(ordered):
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
        row.setProperty("tone", appointment_tone(appointment))
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = (
            lambda event, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )

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

        due_label = QLabel(appointment_status_text(appointment))
        due_label.setObjectName("CalendarDueText")
        due_label.setProperty("tone", appointment_tone(appointment))
        due_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        due_label.setMinimumWidth(110)
        layout.addWidget(due_label)

        view_btn = create_button("View", "subtle", fixed_height=28)
        view_btn.clicked.connect(
            lambda _=None, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        if appointment.status == APPOINTMENT_STATUS_SCHEDULED:
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

    def _make_task_row(self, task, alternate=False):
        row = QFrame()
        row.setObjectName(
            "CalendarTaskRowAlt" if alternate else "CalendarTaskRow"
        )
        row.setProperty("done", task.get("status") == "DONE")

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 11, 18, 11)
        layout.setSpacing(12)
        row.setLayout(layout)

        bar = QFrame()
        bar.setObjectName("CalendarTypeBar")
        bar.setFixedWidth(4)
        bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        palette = bar.palette()
        task_color = "#7C3AED" if task.get("is_group_task") else "#2563EB"
        palette.setColor(QPalette.Window, QColor(task_color))
        bar.setPalette(palette)
        bar.setAutoFillBackground(True)
        layout.addWidget(bar)

        type_badge = QLabel("Task")
        type_badge.setObjectName("CalendarTypeBadge")
        type_badge.setStyleSheet(
            "QLabel#CalendarTypeBadge {"
            f"background-color: {task_color};"
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

        title = QLabel(task.get("title", "Untitled task"))
        title.setObjectName("StrongText")
        text_stack.addWidget(title)

        context = []
        if task.get("scope_label"):
            context.append(task["scope_label"])
        elif task.get("missionary_name"):
            context.append(task["missionary_name"])
        if task.get("project_title"):
            context.append(task["project_title"])
        meta_text = " - ".join(context) if context else "No linked record"
        if task.get("due_date"):
            due_text = task["due_date"].strftime("Due %b %d, %Y")
            meta_text = f"{meta_text} - {due_text}" if meta_text else due_text
        meta = QLabel(meta_text)
        meta.setObjectName("MiniMutedText")
        text_stack.addWidget(meta)
        layout.addLayout(text_stack, stretch=1)

        status = QLabel(
            f"{task.get('priority', 'NORMAL').title()} / "
            f"{task.get('status', 'OPEN').title()}"
        )
        status.setObjectName("CalendarDueText")
        status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status.setMinimumWidth(130)
        layout.addWidget(status)

        edit_btn = create_button("Edit", "subtle", fixed_height=28)
        edit_btn.clicked.connect(
            lambda _=None, task_data=task:
            self._edit_task(task_data)
        )
        if task.get("status") != "DONE":
            done_btn = create_button("Done", "success", fixed_height=28)
            done_btn.setObjectName("CalendarTaskDoneButton")
            done_btn.clicked.connect(
                lambda _=None, task_id=task["id"]:
                self._complete_task(task_id)
            )
            layout.addWidget(done_btn)
        layout.addWidget(edit_btn)

        return row

    def _add_task(self, default_due_date=None, default_work_date=None):
        if default_work_date is None:
            default_work_date = default_due_date
        defaults = (
            {"work_date": default_work_date}
            if default_work_date is not None
            else None
        )
        dialog = TaskDialog(
            SecretaryWorkService(),
            defaults=defaults,
            parent=self,
        )
        if dialog.exec():
            self.load_data()
            self._refresh_office_work_page()
            return True
        return False

    def _edit_task(self, task):
        dialog = TaskDialog(
            SecretaryWorkService(),
            task=task,
            parent=self,
        )
        if dialog.exec():
            self.load_data()
            self._refresh_office_work_page()
            return True
        return False

    def _complete_task(self, task_id):
        if task_id is None:
            return
        try:
            SecretaryWorkService().complete_task(task_id)
            self.load_data()
            self._refresh_office_work_page()
        except Exception:
            logger.exception("Failed to complete calendar task")
            show_message(
                self,
                "Calendar Task",
                "Could not mark that task done.",
                kind="warning",
            )

    def _refresh_office_work_page(self):
        try:
            office_work_page = getattr(
                self.main_window,
                "office_work_page",
                None,
            )
            if office_work_page is not None and hasattr(
                office_work_page,
                "load_data",
            ):
                office_work_page.load_data()
        except Exception:
            logger.exception("Failed to refresh office work after calendar task update")

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
        self._select_combo_value(self.history_status_combo, APPOINTMENT_STATUS_MISSED)
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
        if missionary_id is None or self.main_window is None:
            return

        opener = getattr(
            self.main_window,
            "open_missionary_detail",
            None,
        )
        if callable(opener):
            opener(missionary_id)
