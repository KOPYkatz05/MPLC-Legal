from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import groupby
import time

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QCursor, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from database.models.appointment import (
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
)
from services.appointment_service import AppointmentService
from services.client_view_service import ClientViewService
from services.secretary_work_service import SecretaryWorkService
from ui.foundation.background_loader import LatestRequestLoader
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    BodyLabel,
    InfoLevel,
    FilterBar,
    StatCard,
    StrongBodyLabel,
    SubtitleLabel,
    create_info_badge,
    create_pill_action_button,
    create_pill_button,
    create_button,
    create_card,
    create_combo_box,
    create_scroll_area,
    create_search_edit,
    app_icon,
    show_message,
)
from utils.i18n import tr
from utils.logger import logger


APPOINTMENT_FIELDS = [
    ("interpol_appointment_date", "Interpol", "#7A6EEC"),
    ("biometric_appointment_date", "Biometric", "#D97706"),
    ("pickup_appointment_date", "Pickup", "#059669"),
]

BUCKET_ORDER = ["overdue", "today", "next_7", "later"]
BUCKET_LABEL_KEYS = {
    "overdue": "calendar_bucket_overdue",
    "today": "calendar_bucket_today",
    "next_7": "calendar_bucket_next_7",
    "later": "calendar_bucket_later",
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
    "this_week": "#0EA5AC",
    "total": "#059669",
}
APPOINTMENT_TYPE_TONES = {
    "Interpol": "interpol",
    "Biometric": "biometric",
    "Pickup": "pickup",
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


class CalendarDaySummaryDialog(QMenu):
    def __init__(
        self,
        calendar_page,
        summary_date,
        appointments,
        tasks,
        anchor_widget=None,
    ):
        super().__init__(calendar_page)
        self.calendar_page = calendar_page
        self.summary_date = summary_date
        self.appointments = list(appointments)
        self.tasks = list(tasks)
        self._anchor_widget = anchor_widget

        self.setObjectName("CalendarDaySummaryMenu")
        self._build_ui()

    def _anchor_geometry(self):
        widget = self._anchor_widget
        if widget is None or not widget.isVisible():
            return None
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, widget.size())

    def exec(self, *args):
        position = args[0] if args else self._menu_position()
        self.popup(position)
        return None

    def _menu_position(self):
        if self._anchor_widget is None or not self._anchor_widget.isVisible():
            return QCursor.pos()

        bottom_left = self._anchor_widget.mapToGlobal(
            QPoint(0, self._anchor_widget.height())
        )
        screen = self._anchor_widget.screen() or self.screen()
        available = screen.availableGeometry()
        menu_size = self.sizeHint()
        x = min(bottom_left.x(), available.right() - menu_size.width())
        x = max(available.left(), x)
        y = bottom_left.y() + 6
        if y + menu_size.height() > available.bottom():
            y = self._anchor_widget.mapToGlobal(QPoint(0, 0)).y() - menu_size.height() - 6
        y = max(available.top(), y)
        return QPoint(x, y)

    def _build_ui(self):
        panel = QWidget()
        panel.setObjectName("CalendarDaySummaryPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setFixedWidth(500)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        panel.setLayout(layout)

        header = QWidget()
        header.setObjectName("CalendarDaySummaryHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(16, 14, 16, 10)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = SubtitleLabel(
            self.summary_date.strftime("%A, %B %d, %Y")
        )
        title.setObjectName("CalendarDaySummaryTitle")
        header_layout.addWidget(title)

        subtitle = BodyLabel(tr("calendar_day_summary_subtitle"))
        subtitle.setObjectName("MutedText")
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(8)
        body.setLayout(body_layout)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("CalendarDaySummaryScroll")
        scroll.setMinimumHeight(150)
        scroll.setMaximumHeight(300)
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        appointments_title = QLabel(tr("calendar_appointments"))
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
            empty = QLabel(tr("calendar_no_appointments"))
            empty.setObjectName("CalendarNoAppointmentsLabel")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            body_layout.addWidget(empty)

        tasks_title = QLabel(tr("calendar_tasks"))
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
            empty = QLabel(tr("calendar_no_tasks_planned"))
            empty.setObjectName("CalendarNoTasksLabel")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            body_layout.addWidget(empty)

        footer = QWidget()
        footer.setObjectName("CalendarDaySummaryFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(14, 10, 14, 12)
        footer_layout.setSpacing(8)
        footer.setLayout(footer_layout)
        footer_layout.addStretch()

        close_btn = create_pill_button(tr("common_close"))
        close_btn.setObjectName("CalendarDayCloseButton")
        close_btn.setMinimumWidth(74)
        close_btn.clicked.connect(self.hide)
        footer_layout.addWidget(close_btn)

        add_task_btn = create_pill_button(tr("calendar_add_task"))
        add_task_btn.setObjectName("CalendarDayAddTaskButton")
        add_task_btn.setMinimumWidth(92)
        add_task_btn.clicked.connect(self._add_task)
        footer_layout.addWidget(add_task_btn)
        layout.addWidget(footer)

        action = QWidgetAction(self)
        action.setDefaultWidget(panel)
        self.addAction(action)

    def _add_task(self):
        if self.calendar_page._add_task(default_work_date=self.summary_date):
            self.hide()


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
        return tr("calendar_days_overdue", count=days)
    if days_offset == 0:
        return tr("calendar_due_today")
    return tr("calendar_in_days", count=days_offset)


def appointment_status_text(appointment):
    if appointment.status == APPOINTMENT_STATUS_COMPLETED:
        return tr("calendar_completed")
    if appointment.status == APPOINTMENT_STATUS_MISSED:
        return tr("calendar_missed")
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


def appointment_type_tone(appointment_type):
    return APPOINTMENT_TYPE_TONES.get(appointment_type, "task")


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
        self.client_view_service = ClientViewService()
        self._background_loads_enabled = isinstance(main_window, QWidget)
        self._data_loader = LatestRequestLoader(parent=self)
        self._action_loaders = {}
        self._pending_actions = set()
        self._action_widgets = {}
        self._has_loaded_data = False
        self._last_load_at = 0.0
        self._cache_ttl_seconds = 15.0
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
        self._calendar_render_cache = {}
        self._calendar_summary_counts = {
            "overdue": 0,
            "today": 0,
            "this_week": 0,
        }
        self._history_loaded = False
        self._history_filter_cache = {}
        self._day_summary_menu = None
        self._responsive_size_class = None
        self._calendar_render_timer = QTimer(self)
        self._calendar_render_timer.setSingleShot(True)
        self._calendar_render_timer.setInterval(120)
        self._calendar_render_timer.timeout.connect(self._render_calendar)
        self._history_render_timer = QTimer(self)
        self._history_render_timer.setSingleShot(True)
        self._history_render_timer.setInterval(120)
        self._history_render_timer.timeout.connect(self._render_history)

        self.setup_ui()
        if not self._background_loads_enabled:
            self._load_data_synchronously()

    @staticmethod
    def _size_class_for_width(width):
        if width < 700:
            return "narrow"
        if width < 1100:
            return "compact"
        return "wide"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size_class = self._size_class_for_width(event.size().width())
        if size_class == self._responsive_size_class:
            return
        self._responsive_size_class = size_class
        self._apply_responsive_filter_layout()
        if hasattr(self, "calendar_layout"):
            self._schedule_calendar_render()
        if (
            getattr(self, "_selected_tab", TAB_CALENDAR) == TAB_HISTORY
            and hasattr(self, "history_layout")
        ):
            self._schedule_history_render()

    def _current_size_class(self):
        return self._responsive_size_class or self._size_class_for_width(
            self.width()
        )

    def _apply_responsive_filter_layout(self):
        filter_bar = getattr(self, "history_filter_bar", None)
        if filter_bar is None:
            return
        direction = (
            QBoxLayout.LeftToRight
            if self._current_size_class() == "wide"
            else QBoxLayout.TopToBottom
        )
        filter_bar.layout_.setDirection(direction)
        title_layout = getattr(self, "top_title_layout", None)
        if title_layout is not None:
            title_layout.setDirection(direction)

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self._count_label = QLabel("")
        self._count_label.setObjectName("CalendarCountLabel")

        outer.addWidget(self._build_top_bar())

        self.tab_stack = QStackedWidget()
        self.tab_stack.setObjectName("CalendarTabStack")

        workspace = QFrame()
        workspace.setObjectName("CalendarWorkspace")
        workspace.setAttribute(Qt.WA_StyledBackground, True)
        workspace_layout = QVBoxLayout()
        workspace_layout.setContentsMargins(12, 12, 24, 24)
        workspace_layout.setSpacing(0)
        workspace.setLayout(workspace_layout)
        workspace_layout.addWidget(self.tab_stack)
        outer.addWidget(workspace, stretch=1)

        self._build_calendar_tab()
        self._build_history_tab()
        self._apply_responsive_filter_layout()
        self._select_tab(TAB_CALENDAR)

    def _build_top_bar(self):
        frame = QFrame()
        frame.setObjectName("CalendarTopBar")
        frame.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 12)
        layout.setSpacing(8)
        frame.setLayout(layout)

        title_row = QHBoxLayout()
        self.top_title_layout = title_row
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)
        title = QLabel(tr("calendar_title"))
        title.setObjectName("CalendarTitle")
        subtitle = QLabel(tr("calendar_subtitle"))
        subtitle.setObjectName("CalendarSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        title_row.addLayout(title_stack, stretch=1)
        self._count_label.setWordWrap(True)
        self._count_label.setMinimumWidth(0)
        self._count_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        title_row.addWidget(self._count_label, alignment=Qt.AlignRight)
        layout.addLayout(title_row)

        self._build_top_tabs()
        layout.addWidget(self.tab_bar)
        return frame

    def _build_top_tabs(self):
        self.tab_buttons = {}
        self.tab_button_group = QButtonGroup(self)
        self.tab_control = None

        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("CalendarTopTabs")
        self.tab_bar.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tab_bar.setLayout(layout)

        self.tab_button_group.setExclusive(True)

        for key, title in [
            (TAB_CALENDAR, tr("calendar_tab_calendar")),
            (TAB_HISTORY, tr("calendar_tab_history")),
        ]:
            button = QPushButton(title)
            button.setObjectName("CalendarTabButton")
            button.setCheckable(True)
            button.setFixedHeight(30)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        self.calendar_layout.setContentsMargins(20, 6, 20, 12)
        self.calendar_layout.setSpacing(6)
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
        self.history_layout.setContentsMargins(20, 18, 20, 20)
        self.history_layout.setSpacing(18)
        content.setLayout(self.history_layout)

        scroll.setWidget(content)
        tab_layout.addWidget(scroll, stretch=1)
        self.history_index = self.tab_stack.addWidget(tab)

    def _build_history_filter_bar(self):
        self.history_filter_bar = FilterBar()

        self.history_search_edit = create_search_edit(
            tr("calendar_search_missionary")
        )
        self.history_search_edit.textChanged.connect(
            self._schedule_history_render
        )
        self.history_filter_bar.add_filter(
            self.history_search_edit,
            stretch=1,
        )

        self.history_type_combo = create_combo_box()
        for label, value in self._appointment_type_options():
            self.history_type_combo.addItem(label, value)
        self.history_type_combo.currentIndexChanged.connect(
            lambda _=None: self._schedule_history_render()
        )
        self.history_filter_bar.add_filter(self.history_type_combo)

        self.history_status_combo = create_combo_box()
        for label, value in [
            (tr("calendar_filter_all"), "all"),
            (tr("calendar_completed"), APPOINTMENT_STATUS_COMPLETED),
            (tr("calendar_bucket_overdue"), "overdue"),
            (tr("calendar_missed"), APPOINTMENT_STATUS_MISSED),
        ]:
            self.history_status_combo.addItem(label, value)
        self.history_status_combo.currentIndexChanged.connect(
            lambda _=None: self._schedule_history_render()
        )
        self.history_filter_bar.add_filter(self.history_status_combo)

        self.history_sort_combo = create_combo_box()
        for label, value in [
            (tr("calendar_date_desc"), "desc"),
            (tr("calendar_date_asc"), "asc"),
        ]:
            self.history_sort_combo.addItem(label, value)
        self.history_sort_combo.currentIndexChanged.connect(
            lambda _=None: self._schedule_history_render()
        )
        self.history_filter_bar.add_filter(self.history_sort_combo)

        self.history_date_label = QLabel("")
        self.history_date_label.setObjectName("CalendarHistoryDateFilter")
        self.history_date_label.setVisible(False)
        self.history_filter_bar.add_filter(self.history_date_label)

        self.clear_history_date_btn = create_button(
            tr("calendar_clear_date"),
            "subtle",
            fixed_height=30,
        )
        self.clear_history_date_btn.clicked.connect(
            self._clear_history_date_filter
        )
        self.clear_history_date_btn.setVisible(False)
        self.history_filter_bar.add_filter(self.clear_history_date_btn)

    def load_data(self):
        """Compatibility entry point for mutation-triggered forced refreshes."""
        if self._background_loads_enabled:
            return self.request_refresh(force=True)
        self._load_data_synchronously()
        return True

    def request_refresh(self, force=False):
        cache_is_fresh = (
            self._has_loaded_data
            and time.monotonic() - self._last_load_at
            < self._cache_ttl_seconds
        )
        if cache_is_fresh and not force:
            return False

        if not self._background_loads_enabled:
            self._load_data_synchronously()
            return True
        if self._data_loader.busy and not force:
            return False

        self._data_loader.request(
            self._fetch_calendar_snapshot,
            on_success=self._apply_calendar_snapshot,
            on_error=self._calendar_refresh_failed,
        )
        return True

    def _fetch_calendar_snapshot(self):
        snapshot = self.client_view_service.get_calendar_snapshot()
        return {
            "appointments": self._appointment_items_from_snapshots(
                snapshot.get("scheduled") or []
            ),
            "history": self._appointment_items_from_snapshots(
                snapshot.get("history") or [],
                newest_first=True,
            ),
            "tasks": list(snapshot.get("tasks") or []),
        }

    def _load_data_synchronously(self):
        try:
            self._apply_calendar_snapshot({
                "appointments": self._collect_appointments(),
                "history": self._collect_history_appointments(),
                "tasks": self._collect_tasks(),
            })
        except Exception:
            logger.exception("Failed to load calendar data")

    def _apply_calendar_snapshot(self, snapshot):
        self._appointments = list(snapshot.get("appointments") or [])
        self._history_appointments = list(snapshot.get("history") or [])
        self._tasks = list(snapshot.get("tasks") or [])
        self._calendar_summary_counts = self._build_summary_counts(
            self._appointments
        )
        self._history_filter_cache = {}
        self._count_label.setText(
            tr("calendar_scheduled_count", count=len(self._appointments))
        )
        self._render_calendar()
        self._history_loaded = False
        if self._selected_tab == TAB_HISTORY:
            self._render_history()
        else:
            timer = getattr(self, "_history_render_timer", None)
            if timer is not None:
                timer.stop()
        self._has_loaded_data = True
        self._last_load_at = time.monotonic()

    @staticmethod
    def _calendar_refresh_failed(error):
        logger.error("Failed to refresh calendar in background: %s", error)

    def _register_action_widget(self, kind, item_id, widget):
        if item_id is None:
            return
        key = (kind, item_id)
        self._action_widgets.setdefault(key, []).append(widget)
        widget.setEnabled(key not in self._pending_actions)

    def _set_action_pending(self, key, pending):
        if pending:
            self._pending_actions.add(key)
        else:
            self._pending_actions.discard(key)
        for widget in self._action_widgets.get(key, []):
            try:
                widget.setEnabled(not pending)
            except RuntimeError:
                continue

    def _run_action(
        self,
        kind,
        item_id,
        operation,
        on_success,
        on_error,
    ):
        if not self._background_loads_enabled:
            try:
                result = operation()
            except Exception as error:
                on_error(error)
            else:
                on_success(result)
            return True

        key = (kind, item_id)
        if key in self._pending_actions:
            return False
        loader = self._action_loaders.get(key)
        if loader is None:
            loader = LatestRequestLoader(parent=self)
            self._action_loaders[key] = loader
        self._data_loader.cancel()
        self._set_action_pending(key, True)

        def finish(result):
            self._set_action_pending(key, False)
            on_success(result)

        def fail(error):
            self._set_action_pending(key, False)
            on_error(error)

        loader.request(
            operation,
            on_success=finish,
            on_error=fail,
        )
        return True

    def _appointment_type_options(self):
        return [
            (tr("calendar_all_types"), "All Types"),
            ("Interpol", "Interpol"),
            (tr("calendar_biometric"), "Biometric"),
            (tr("calendar_pickup"), "Pickup"),
        ]

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
        if key == TAB_HISTORY and not self._history_loaded:
            self._render_history()
        if self.tab_control is not None:
            current_key = getattr(self.tab_control, "currentRouteKey", lambda: None)()
            if current_key != key:
                self.tab_control.setCurrentItem(key)
        elif key in self.tab_buttons:
            self.tab_buttons[key].setChecked(True)
        self._refresh_tab_buttons()

    def _refresh_tab_buttons(self):
        for tab_key, button in self.tab_buttons.items():
            is_active = tab_key == self._selected_tab
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _schedule_calendar_render(self):
        timer = getattr(self, "_calendar_render_timer", None)
        if timer is None:
            self._render_calendar()
            return
        timer.start()

    def _schedule_history_render(self):
        timer = getattr(self, "_history_render_timer", None)
        if timer is None:
            self._render_history()
            return
        timer.start()

    def _render_calendar(self):
        self._clear_layout(self.calendar_layout)
        self._build_summary_cards()

        visible_dates = visible_range_for_mode(
            self._calendar_mode,
            self._anchor_date,
        )
        visible_set = set(visible_dates)
        filtered = self._apply_calendar_filters(self._appointments)
        task_items = self._tasks_by_date(self._tasks)
        scheduled_filtered = [
            item for item in filtered if item.bucket != "overdue"
        ]
        self._calendar_render_cache = {
            "anchor_date": self._anchor_date,
            "calendar_mode": self._calendar_mode,
            "visible_dates": visible_dates,
            "visible_set": visible_set,
            "filtered_appointments": scheduled_filtered,
            "appointments_by_date": self._appointments_by_date(scheduled_filtered),
            "tasks_by_date": task_items,
        }
        calendar_stack = QWidget()
        calendar_stack.setObjectName("CalendarStack")
        stack_layout = QVBoxLayout()
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(6)
        calendar_stack.setLayout(stack_layout)

        stack_layout.addWidget(self._build_calendar_toolbar())

        grid_card = create_card()
        grid_card.setObjectName("CalendarGridCard")
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(10, 10, 10, 10)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setVerticalSpacing(6)
        grid_card.setLayout(grid_layout)

        for column, label in enumerate(WEEKDAY_LABELS):
            header = QLabel(label.upper())
            header.setObjectName("CalendarWeekdayHeader")
            header.setAlignment(Qt.AlignCenter)
            grid_layout.addWidget(header, 0, column)
            grid_layout.setColumnStretch(column, 1)

        day_items = self._calendar_render_cache["appointments_by_date"]
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

        self.calendar_layout.addWidget(calendar_stack)

        has_visible_items = any(
            day_items.get(day) for day in visible_dates
        )
        has_visible_tasks = any(
            task_items.get(day) for day in visible_dates
        )

        if not self._appointments and not self._tasks:
            self.calendar_layout.addWidget(
                self._make_empty_state(tr("calendar_empty_no_scheduled"))
            )
        elif not has_visible_items and not has_visible_tasks:
            self.calendar_layout.addWidget(
                self._make_empty_state(
                    tr("calendar_empty_range")
                )
            )

        self.calendar_layout.addStretch()

    def _build_summary_cards(self):
        counts = self._calendar_summary_counts

        row = QGridLayout()
        row.setSpacing(10)

        cards = [
            ("overdue", counts["overdue"], "Overdue"),
            ("today", counts["today"], "Today"),
            ("this_week", counts["this_week"], "This Week"),
            ("total", len(self._appointments), "Total Scheduled"),
        ]

        size_class = self._current_size_class()
        columns = 4 if size_class == "wide" else (2 if size_class == "compact" else 1)
        for index, (key, value, title) in enumerate(cards):
            card = StatCard(
                value,
                title,
                color=SUMMARY_COLORS[key],
            )
            card.setObjectName("CalendarSummaryCard")
            card.setMinimumHeight(58)
            card.setMaximumHeight(62)
            card.layout().setContentsMargins(14, 6, 14, 6)
            card.layout().setSpacing(1)
            row.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            row.setColumnStretch(column, 1)

        wrapper = QWidget()
        wrapper.setObjectName("CalendarSummaryRow")
        wrapper.setLayout(row)
        self.calendar_layout.addWidget(wrapper)

    def _build_summary_counts(self, appointments):
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

        for item in appointments:
            if item.bucket == "overdue":
                counts["overdue"] += 1
            if item.date == today:
                counts["today"] += 1
            if item.date in week_dates:
                counts["this_week"] += 1
        return counts

    def _build_calendar_toolbar(self):
        toolbar = create_card(object_name="CalendarToolbar")
        toolbar.setObjectName("CalendarToolbar")
        layout = QGridLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        toolbar.setLayout(layout)

        previous_btn = self._make_nav_arrow_button(
            "LEFT_ARROW",
            tr("calendar_previous"),
        )
        previous_btn.clicked.connect(self._go_previous_range)

        today_btn = create_pill_button(tr("calendar_today"))
        today_btn.setObjectName("CalendarToolbarPillButton")
        today_btn.setMinimumWidth(62)
        today_btn.clicked.connect(self._go_today)

        next_btn = self._make_nav_arrow_button(
            "RIGHT_ARROW",
            tr("calendar_next"),
        )
        next_btn.clicked.connect(self._go_next_range)

        self.range_title_label = QLabel(self._calendar_range_title())
        self.range_title_label.setObjectName("CalendarRangeTitle")
        self.range_title_label.setAlignment(Qt.AlignCenter)

        self.calendar_search_edit = create_search_edit(
            tr("calendar_search_calendar")
        )
        self.calendar_search_edit.setText(
            getattr(self, "_calendar_search_text", "")
        )
        self.calendar_search_edit.textChanged.connect(
            lambda _=None: self._calendar_search_changed(
                self.calendar_search_edit.text()
            )
        )

        self.calendar_type_combo = create_combo_box()
        selected_type = getattr(self, "_calendar_type_filter", "All Types")
        for label, value in self._appointment_type_options():
            self.calendar_type_combo.addItem(label, value)
        self._select_combo_value(self.calendar_type_combo, selected_type)
        self.calendar_type_combo.currentIndexChanged.connect(
            lambda _=None: self._calendar_type_changed()
        )

        add_task_btn = create_pill_button(tr("calendar_add_task"))
        add_task_btn.setObjectName("CalendarAddTaskButton")
        add_task_btn.setMinimumWidth(84)
        add_task_btn.clicked.connect(
            lambda checked=False: self._add_task()
        )
        size_class = self._current_size_class()
        if size_class == "wide":
            widgets = [
                previous_btn,
                today_btn,
                next_btn,
                self.range_title_label,
                self.calendar_search_edit,
                self.calendar_type_combo,
                add_task_btn,
            ]
            for column, widget in enumerate(widgets):
                layout.addWidget(widget, 0, column)
            layout.setColumnStretch(3, 1)
            layout.setColumnStretch(4, 1)
        else:
            layout.addWidget(previous_btn, 0, 0)
            layout.addWidget(today_btn, 0, 1)
            layout.addWidget(next_btn, 0, 2)
            layout.addWidget(self.range_title_label, 0, 3, 1, 3)
            layout.addWidget(self.calendar_search_edit, 1, 0, 1, 6)
            if size_class == "narrow":
                layout.addWidget(self.calendar_type_combo, 2, 0, 1, 3)
                layout.addWidget(add_task_btn, 2, 3, 1, 3)
            else:
                layout.addWidget(self.calendar_type_combo, 1, 6)
                layout.addWidget(add_task_btn, 1, 7)
            layout.setColumnStretch(3, 1)

        return toolbar

    def _make_nav_arrow_button(self, icon_name, tooltip):
        slot = "calendar.previous" if icon_name == "LEFT_ARROW" else "calendar.next"
        fallback = "<" if icon_name == "LEFT_ARROW" else ">"
        button = create_pill_button(fallback)
        button.setObjectName("CalendarNavPillButton")
        button.setFixedSize(34, 30)
        lucide = app_icon(slot, size=18)
        if lucide is not None and not lucide.isNull():
            button.setIcon(lucide)
            button.setIconSize(QSize(16, 16))
            button.setText("")
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

    def _build_overdue_strip(self, overdue, visible_set):
        _ = visible_set
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
        cell.setMinimumWidth(0)
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cell.mousePressEvent = (
            lambda event, filter_date=day, anchor=cell:
            self._show_calendar_day_details(
                filter_date,
                anchor_widget=anchor,
            )
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
        cell_padding = 6 if self._current_size_class() != "wide" else 10
        layout.setContentsMargins(cell_padding, cell_padding, cell_padding, cell_padding)
        layout.setSpacing(4 if cell_padding == 6 else 6)
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

        max_visible = 2 if mode == CALENDAR_MODE_MONTH and total_items > 3 else 3
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
            overflow.setMinimumWidth(0)
            overflow.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            overflow.clicked.connect(
                lambda checked=False, filter_date=day, anchor=overflow:
                self._show_calendar_day_details(
                    filter_date,
                    anchor_widget=anchor,
                )
            )
            layout.addWidget(overflow)

        layout.addStretch()
        return cell

    def _make_calendar_chip(self, appointment, compact=False):
        text = self._calendar_chip_text(appointment, compact)
        pill = create_pill_action_button(
            text,
            accent=None,
            leading_icon=None,
            drag_payload=None,
            object_name="CalendarAppointmentChip",
        )
        pill.setFixedHeight(30)
        pill.setMinimumWidth(0)
        pill.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        pill.label.setMinimumWidth(0)
        pill.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pill.layout().setContentsMargins(6, 4, 6, 4)
        pill.layout().setSpacing(4)
        pill.setToolTip(
            f"{appointment.type} appointment for {appointment.full_name}"
        )
        pill.clicked.connect(
            lambda checked=False, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        self._register_action_widget(
            "appointment",
            appointment.appointment_id,
            pill,
        )
        return pill

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
                tr("calendar_task_message_title"),
                tr("calendar_task_move_failed"),
                kind="warning",
            )

    def _calendar_chip_text(self, appointment, compact=False):
        limit = 28 if compact else 24
        name = appointment.full_name
        if len(name) > limit:
            name = f"{name[:limit - 3]}..."

        separator = ":" if compact else "-"
        return f"{appointment.type} {separator} {name}"

    def _task_chip_text(self, task):
        title = task.get("title", "") or tr("calendar_untitled_task")
        limit = 24
        if len(title) > limit:
            title = f"{title[:limit - 3]}..."
        return title

    def _make_task_chip(self, task):
        text = self._task_chip_text(task)
        scope = task.get("scope_label") or task.get("missionary_name") or ""
        tooltip = tr(
            "calendar_task_tooltip",
            title=task.get("title", "") or tr("calendar_untitled_task"),
        )
        if task.get("due_date"):
            tooltip = (
                f"{tooltip} - "
                f"{tr('calendar_due_date', date=task['due_date'].strftime('%b %d, %Y'))}"
            )
        if scope:
            tooltip = f"{tooltip} - {scope}"

        actions = []
        if task.get("status") not in {"DONE", "ARCHIVED"}:
            actions.append(
                {
                    "tooltip": tr("common_done"),
                    "icon": "check",
                    "fallback": "",
                    "callback": lambda task_id=task["id"]: self._complete_task(task_id),
                }
            )

        pill = create_pill_action_button(
            text,
            actions=actions,
            drag_payload=task.get("id"),
            drag_mime_type=TASK_DRAG_MIME,
            object_name="CalendarTaskChip",
        )
        pill.setFixedHeight(30)
        pill.setMinimumWidth(0)
        pill.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        pill.label.setMinimumWidth(0)
        pill.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pill.subtitle.setMinimumWidth(0)
        pill.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pill.layout().setContentsMargins(6, 4, 6, 4)
        pill.layout().setSpacing(4)
        pill.setToolTip(tooltip)
        pill.setProperty("done", task.get("status") == "DONE")
        pill.clicked.connect(
            lambda checked=False, task_data=task:
            self._edit_task(task_data)
        )
        self._register_action_widget("task", task.get("id"), pill)
        return pill

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
        self._schedule_calendar_render()

    def _go_previous_range(self):
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._anchor_date = add_months(self._anchor_date, -1)
        self._schedule_calendar_render()

    def _go_next_range(self):
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._anchor_date = add_months(self._anchor_date, 1)
        self._schedule_calendar_render()

    def _go_today(self):
        self._anchor_date = date.today()
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._schedule_calendar_render()

    def _calendar_type_changed(self):
        self._calendar_type_filter = (
            self.calendar_type_combo.currentData() or "All Types"
        )
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._schedule_calendar_render()

    def _calendar_search_changed(self, text):
        self._calendar_search_text = text
        self._calendar_detail_date = None
        self._show_overdue_detail = False
        self._schedule_calendar_render()

    def _show_calendar_day_details(self, filter_date, anchor_widget=None):
        self._show_overdue_detail = False
        cache = self._calendar_render_cache or {}
        appointments = cache.get("appointments_by_date", {}).get(filter_date, [])
        tasks = cache.get("tasks_by_date", {}).get(filter_date, [])
        dialog = CalendarDaySummaryDialog(
            self,
            filter_date,
            appointments,
            tasks,
            anchor_widget=anchor_widget,
        )
        if self._day_summary_menu is not None:
            self._day_summary_menu.hide()
        self._day_summary_menu = dialog
        if hasattr(dialog, "aboutToHide"):
            dialog.aboutToHide.connect(
                lambda menu=dialog: self._clear_day_summary_menu(menu)
            )
        dialog.exec()

    def _clear_day_summary_menu(self, menu):
        if self._day_summary_menu is menu:
            self._day_summary_menu = None

    def _show_overdue_calendar_details(self, anchor_widget=None):
        _ = anchor_widget
        self._history_exact_date = None
        self._select_combo_value(self.history_status_combo, "overdue")
        self._select_tab(TAB_HISTORY)

    def _render_history(self):
        if not hasattr(self, "history_layout"):
            return

        self._clear_layout(self.history_layout)
        self._sync_history_date_filter_ui()

        completed_items = [
            item
            for item in self._apply_history_filters(self._history_appointments)
            if item.status == APPOINTMENT_STATUS_COMPLETED
        ]
        overdue_items = [
            item
            for item in self._apply_history_filters(self._appointments)
            if item.bucket == "overdue"
        ]
        has_source_items = bool(self._history_appointments or overdue_items)
        if not has_source_items:
            self.history_layout.addWidget(
                self._make_empty_state(tr("calendar_history_empty"))
            )
            self.history_layout.addStretch()
            self._history_loaded = True
            return

        if not completed_items and not overdue_items:
            self.history_layout.addWidget(
                self._make_empty_state(tr("calendar_history_no_matches"))
            )
            self.history_layout.addStretch()
            self._history_loaded = True
            return

        self.history_layout.addWidget(
            self._make_history_board(completed_items, overdue_items)
        )
        self.history_layout.addStretch()
        self._history_loaded = True

    def _apply_history_filters(self, appointments):
        query = self.history_search_edit.text().strip().casefold()
        type_filter = self.history_type_combo.currentData() or "All Types"
        status_filter = self.history_status_combo.currentData() or "all"
        sort_direction = self.history_sort_combo.currentData() or "asc"
        cache_key = (
            id(appointments),
            self._history_exact_date,
            query,
            type_filter,
            status_filter,
            sort_direction,
        )
        cache = self._history_filter_cache
        if cache_key in cache:
            return cache[cache_key]

        filtered = self._compute_history_filters(
            appointments,
            query=query,
            type_filter=type_filter,
            status_filter=status_filter,
        )
        reverse = sort_direction == "desc"
        result = sorted(
            filtered,
            key=lambda item: (
                item.date,
                item.type,
                item.full_name.casefold(),
            ),
            reverse=reverse,
        )
        cache[cache_key] = result
        return result

    def _compute_history_filters(
        self,
        appointments,
        *,
        query,
        type_filter,
        status_filter,
    ):
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
        return filtered

    def _matches_status_filter(self, item, status_filter):
        if status_filter == "all":
            return True
        if status_filter == "overdue":
            return item.bucket == "overdue"
        return item.status == status_filter

    def _make_history_board(self, completed_items, overdue_items):
        board = QWidget()
        board.setObjectName("CalendarHistoryBoard")
        direction = (
            QBoxLayout.LeftToRight
            if self._current_size_class() == "wide"
            else QBoxLayout.TopToBottom
        )
        layout = QBoxLayout(direction)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        board.setLayout(layout)

        layout.addWidget(
            self._make_history_column(
                tr("calendar_completed"),
                completed_items,
                "success",
                tr("calendar_history_no_completed"),
            ),
            stretch=1,
        )
        layout.addWidget(
            self._make_history_column(
                tr("calendar_bucket_overdue"),
                overdue_items,
                "danger",
                tr("calendar_history_no_overdue"),
            ),
            stretch=1,
        )
        return board

    def _make_history_column(self, title_text, appointments, tone, empty_text):
        column = create_card(object_name="CalendarHistoryColumn")
        column.setObjectName("CalendarHistoryColumn")
        column.setProperty("tone", tone)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        column.setLayout(layout)

        header = QFrame()
        header.setObjectName("CalendarHistoryColumnHeader")
        header.setProperty("tone", tone)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 14, 16, 10)
        header_layout.setSpacing(8)
        header.setLayout(header_layout)

        title = QLabel(title_text.upper())
        title.setObjectName("CalendarSectionTitle")
        title.setProperty("tone", tone)
        header_layout.addWidget(title)

        count_label = QLabel(str(len(appointments)))
        count_label.setObjectName("CalendarSectionCount")
        count_label.setProperty("tone", tone)
        header_layout.addWidget(count_label)
        header_layout.addStretch()
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(10, 10, 10, 12)
        body_layout.setSpacing(10)
        body.setLayout(body_layout)
        layout.addWidget(body)

        if not appointments:
            empty = QLabel(empty_text)
            empty.setObjectName("MutedText")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setContentsMargins(12, 24, 12, 24)
            body_layout.addWidget(empty)
            body_layout.addStretch()
            return column

        for appt_date, day_items in groupby(
            appointments,
            key=lambda item: item.date,
        ):
            body_layout.addWidget(
                self._make_history_day_group(appt_date, list(day_items), tone)
            )
        body_layout.addStretch()
        return column

    def _make_history_day_group(self, appt_date, appointments, tone):
        group = QFrame()
        group.setObjectName("CalendarHistoryDayGroup")
        group.setProperty("tone", tone)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        group.setLayout(layout)

        header = QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 2)
        header.setSpacing(8)

        date_label = QLabel(appt_date.strftime("%A, %B %d, %Y"))
        date_label.setObjectName("PanelTitle")
        header.addWidget(date_label)
        header.addStretch()

        distance_label = QLabel(appointment_status_text(appointments[0]))
        distance_label.setObjectName("AlertBadge")
        distance_label.setProperty("tone", appointment_tone(appointments[0]))
        header.addWidget(distance_label)

        header_wrapper = QWidget()
        header_wrapper.setLayout(header)
        layout.addWidget(header_wrapper)

        for index, appointment in enumerate(appointments):
            layout.addWidget(
                self._make_appointment_row(
                    appointment,
                    alternate=index % 2 == 1,
                )
            )
        return group

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
        title_text = (
            tr("calendar_completed")
            if status == APPOINTMENT_STATUS_COMPLETED
            else tr("calendar_missed")
        )

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
        card = create_card(object_name="CalendarHistoryFocusCard")
        card.setObjectName("CalendarHistoryFocusCard")

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card.setLayout(card_layout)

        header = QFrame()
        header.setObjectName("CalendarHistoryFocusHeader")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(18, 14, 18, 10)
        header_layout.setSpacing(10)
        header.setLayout(header_layout)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)

        title = QLabel(appointments[0].full_name)
        title.setObjectName("CalendarHistoryFocusTitle")
        title_stack.addWidget(title)

        header_layout.addLayout(title_stack, stretch=1)
        header_layout.addStretch()
        header_layout.addWidget(
            create_info_badge(
                f"{len(appointments)} appointment"
                f"{'s' if len(appointments) != 1 else ''}",
                level=appointment_info_level(appointments[0]),
            )
        )
        card_layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body.setLayout(body_layout)
        card.viewLayout = body_layout
        card_layout.addWidget(body)

        content = QWidget()
        content.setObjectName("CalendarHistoryFocusList")
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        content.setLayout(list_layout)
        body_layout.addWidget(content)

        subtitle = BodyLabel(
            appointments[0].current_stage or tr("calendar_no_current_stage")
        )
        subtitle.setObjectName("CalendarHistoryFocusMeta")
        subtitle.setContentsMargins(18, 10, 18, 10)
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
        type_badge.setProperty(
            "tone", appointment_type_tone(appointment.type)
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
                tr(
                    "calendar_stage_meta",
                    value=(
                        appointment.current_stage
                        or tr("calendar_no_current_stage")
                    ),
                )
            )
        )

        left_wrapper = QWidget()
        left_wrapper.setLayout(left_stack)
        layout.addWidget(left_wrapper, stretch=1)

        view_btn = create_pill_button(tr("calendar_view"))
        view_btn.setFixedHeight(28)
        view_btn.clicked.connect(
            lambda _=None, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        if appointment.status == APPOINTMENT_STATUS_SCHEDULED:
            complete_btn = create_pill_button(tr("calendar_complete"))
            complete_btn.setObjectName("CalendarCompleteAppointmentButton")
            complete_btn.setFixedHeight(28)
            complete_btn.clicked.connect(
                lambda _=None, appt=appointment:
                self._complete_appointment(appt)
            )
            missed_btn = create_pill_button(tr("calendar_missed"))
            missed_btn.setObjectName("CalendarMissedAppointmentButton")
            missed_btn.setFixedHeight(28)
            missed_btn.clicked.connect(
                lambda _=None, appt=appointment:
                self._miss_appointment(appt)
            )
            layout.addWidget(complete_btn)
            layout.addWidget(missed_btn)
        layout.addWidget(view_btn)

        self._register_action_widget(
            "appointment",
            appointment.appointment_id,
            row,
        )
        return row

    def _make_section_header(self, bucket, count):
        row = QFrame()
        row.setObjectName("CalendarSectionHeader")
        row.setProperty("tone", BUCKET_TONES[bucket])

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 2)
        layout.setSpacing(8)
        row.setLayout(layout)

        title = QLabel(tr(BUCKET_LABEL_KEYS[bucket]).upper())
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

        title = QLabel(tr("calendar_overdue_scheduled"))
        title.setObjectName("PanelTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        badge = QLabel(
            tr("calendar_need_action_count", count=len(appointments))
        )
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
        subtitle_parts = [
            tr("calendar_cita_type_meta", type=appointment.type),
            appointment_status_text(appointment),
        ]
        subtitle = "  |  ".join(part for part in subtitle_parts if part)

        actions = [
            {
                "tooltip": tr("calendar_view"),
                "icon": "panel-top-open",
                "fallback": "",
                "callback": lambda _=False, m_id=appointment.missionary_id:
                self._open_missionary(m_id),
            }
        ]
        if appointment.status == APPOINTMENT_STATUS_SCHEDULED:
            actions = [
                {
                    "tooltip": tr("calendar_complete"),
                    "icon": "check",
                    "fallback": "",
                    "callback": lambda _=False, appt=appointment:
                    self._complete_appointment(appt),
                },
                {
                    "tooltip": tr("calendar_missed"),
                    "icon": "x",
                    "fallback": "",
                    "callback": lambda _=False, appt=appointment:
                    self._miss_appointment(appt),
                },
                *actions,
            ]

        row = create_pill_action_button(
            appointment.full_name,
            subtitle=subtitle,
            actions=actions,
            accent=appointment.color,
            object_name=(
                "CalendarAppointmentRowAlt"
                if alternate
                else "CalendarAppointmentRow"
            ),
        )
        row.setProperty("tone", appointment_tone(appointment))
        row.setFixedHeight(50)
        row.setMinimumWidth(0)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(
            lambda _=False, m_id=appointment.missionary_id:
            self._open_missionary(m_id)
        )
        self._register_action_widget(
            "appointment",
            appointment.appointment_id,
            row,
        )
        return row

    def _make_task_row(self, task, alternate=False):
        subtitle_parts = []
        scope = task.get("scope_label") or task.get("missionary_name")
        if scope:
            subtitle_parts.append(scope)
        if task.get("due_date"):
            subtitle_parts.append(
                tr("calendar_due_date", date=task["due_date"].strftime("%b %d, %Y"))
            )
        subtitle_parts.append(task.get("status", "").title())
        subtitle = "  |  ".join(part for part in subtitle_parts if part)

        actions = []
        if task.get("status") != "DONE":
            actions.append(
                {
                    "tooltip": tr("common_done"),
                    "icon": "check",
                    "fallback": "",
                    "callback": lambda _=False, task_id=task["id"]:
                    self._complete_task(task_id),
                }
            )
        actions.append(
            {
                "tooltip": tr("calendar_edit"),
                "icon": "pencil",
                "fallback": "",
                "callback": lambda _=False, task_data=task:
                self._edit_task(task_data),
            }
        )

        row = create_pill_action_button(
            task.get("title", tr("calendar_untitled_task")),
            subtitle=subtitle,
            actions=actions,
            accent="#0EA5AC" if not task.get("is_group_task") else "#7A6EEC",
            object_name=("CalendarTaskRowAlt" if alternate else "CalendarTaskRow"),
        )
        row.setProperty("done", task.get("status") == "DONE")
        row.setFixedHeight(50)
        row.setMinimumWidth(0)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(
            lambda _=False, task_data=task:
            self._edit_task(task_data)
        )
        self._register_action_widget("task", task.get("id"), row)
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

        def completed(_result):
            if self._background_loads_enabled:
                self.apply_task_status(task_id, "DONE")
            else:
                self.load_data()
            self._pending_peer_task_status = (task_id, "DONE")
            self._refresh_office_work_page()

        def failed(error):
            logger.error(
                "Failed to complete calendar task: %s",
                error,
            )
            show_message(
                self,
                tr("calendar_task_message_title"),
                tr("calendar_task_complete_failed"),
                kind="warning",
            )

        self._run_action(
            "task",
            task_id,
            lambda: SecretaryWorkService().complete_task(task_id),
            completed,
            failed,
        )

    def apply_task_status(self, task_id, status):
        changed = False
        updated_tasks = []
        for task in self._tasks:
            if task.get("id") != task_id:
                updated_tasks.append(task)
                continue
            updated = dict(task)
            if status not in {None, "ARCHIVED"}:
                updated["status"] = status
                updated_tasks.append(updated)
            changed = True
        if not changed:
            return False
        self._tasks = updated_tasks
        self._render_calendar()
        return True

    def _refresh_office_work_page(self, task_id=None, status=None):
        try:
            if task_id is None and status is None:
                task_id, status = getattr(
                    self,
                    "_pending_peer_task_status",
                    (None, None),
                )
                self._pending_peer_task_status = (None, None)
            office_work_page = getattr(
                self.main_window,
                "office_work_page",
                None,
            )
            if office_work_page is None:
                return
            patch_status = getattr(
                office_work_page,
                "apply_task_status",
                None,
            )
            if task_id is not None and status and callable(patch_status):
                patch_status(task_id, status)
            request_refresh = getattr(
                office_work_page,
                "request_refresh",
                None,
            )
            if callable(request_refresh):
                request_refresh(force=True)
                return
            load_data = getattr(office_work_page, "load_data", None)
            if callable(load_data):
                load_data()
        except Exception:
            logger.exception("Failed to refresh office work after calendar task update")

    def _complete_appointment(self, appointment):
        if not appointment.appointment_id:
            return

        def completed(_result):
            show_message(
                self,
                tr("calendar_appointment_completed_title"),
                tr(
                    "calendar_appointment_completed_message",
                    type=appointment.type,
                ),
            )
            self._apply_completed_appointment(appointment)

        def failed(error):
            logger.error("Failed to complete appointment: %s", error)
            show_message(
                self,
                tr("calendar_appointment_error_title"),
                tr("calendar_appointment_complete_failed"),
                kind="critical",
            )

        self._run_action(
            "appointment",
            appointment.appointment_id,
            lambda: AppointmentService().complete_appointment(
                appointment.appointment_id
            ),
            completed,
            failed,
        )

    def _apply_completed_appointment(self, appointment):
        """Update calendar state after completion without a full data reload."""
        self._apply_appointment_status(
            appointment,
            APPOINTMENT_STATUS_COMPLETED,
        )

    def _apply_appointment_status(self, appointment, status):
        completed = replace(
            appointment,
            status=status,
        )
        appointment_id = appointment.appointment_id
        self._appointments = [
            item
            for item in self._appointments
            if item.appointment_id != appointment_id
        ]
        self._history_appointments = [
            item
            for item in self._history_appointments
            if item.appointment_id != appointment_id
        ]
        self._history_appointments.insert(0, completed)
        self._calendar_summary_counts = self._build_summary_counts(
            self._appointments
        )
        self._history_filter_cache = {}
        self._count_label.setText(
            tr("calendar_scheduled_count", count=len(self._appointments))
        )
        self._render_calendar()
        self._history_loaded = False
        if self._selected_tab == TAB_HISTORY:
            self._render_history()

    def _miss_appointment(self, appointment):
        if not appointment.appointment_id:
            return

        confirm = show_message(
            self,
            tr("calendar_mark_missed_title"),
            tr("calendar_mark_missed_message", type=appointment.type),
            kind="question",
            buttons="yes_no",
        )
        if confirm not in {1, 16384}:
            return

        def missed(_result):
            show_message(
                self,
                tr("calendar_appointment_missed_title"),
                tr(
                    "calendar_appointment_missed_message",
                    type=appointment.type,
                ),
            )
            self._apply_appointment_status(
                appointment,
                APPOINTMENT_STATUS_MISSED,
            )
            self.load_data()

        def failed(error):
            logger.error("Failed to mark appointment missed: %s", error)
            show_message(
                self,
                tr("calendar_appointment_error_title"),
                tr("calendar_appointment_missed_failed"),
                kind="critical",
            )

        self._run_action(
            "appointment",
            appointment.appointment_id,
            lambda: AppointmentService().miss_appointment(
                appointment.appointment_id
            ),
            missed,
            failed,
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
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(6)
        card.setLayout(layout)

        title = QLabel(message)
        title.setObjectName("PanelTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(title)

        detail = QLabel(tr("calendar_empty_state_detail"))
        detail.setObjectName("MutedText")
        detail.setAlignment(Qt.AlignCenter)
        detail.setWordWrap(True)
        detail.setMinimumWidth(0)
        detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(detail)

        return card

    def _select_combo_value(self, combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def capture_navigation_state(self):
        return {
            "selected_tab": self._selected_tab,
            "calendar_mode": self._calendar_mode,
            "anchor_date": self._anchor_date,
            "calendar_search_text": self._calendar_search_text,
            "calendar_type_filter": self._calendar_type_filter,
            "calendar_detail_date": self._calendar_detail_date,
            "show_overdue_detail": self._show_overdue_detail,
            "history_exact_date": self._history_exact_date,
            "history_search_text": self.history_search_edit.text() if hasattr(self, "history_search_edit") else "",
            "history_type_filter": self.history_type_combo.currentData() if hasattr(self, "history_type_combo") else "All Types",
            "history_status_filter": self.history_status_combo.currentData() if hasattr(self, "history_status_combo") else "all",
            "history_sort_filter": self.history_sort_combo.currentData() if hasattr(self, "history_sort_combo") else "asc",
        }

    def restore_navigation_state(self, state):
        if not state:
            return

        controls = (
            getattr(self, "calendar_search_edit", None),
            getattr(self, "calendar_type_combo", None),
            getattr(self, "history_search_edit", None),
            getattr(self, "history_type_combo", None),
            getattr(self, "history_status_combo", None),
            getattr(self, "history_sort_combo", None),
        )
        for control in controls:
            if control is not None and hasattr(control, "blockSignals"):
                control.blockSignals(True)

        try:
            self._selected_tab = state.get("selected_tab", TAB_CALENDAR)
            self._calendar_mode = state.get("calendar_mode", CALENDAR_MODE_MONTH)
            self._anchor_date = state.get("anchor_date", date.today())
            self._calendar_search_text = state.get("calendar_search_text", "")
            self._calendar_type_filter = state.get("calendar_type_filter", "All Types")
            self._calendar_detail_date = state.get("calendar_detail_date")
            self._show_overdue_detail = state.get("show_overdue_detail", False)
            self._history_exact_date = state.get("history_exact_date")

            if hasattr(self, "calendar_search_edit"):
                self.calendar_search_edit.setText(self._calendar_search_text)
            if hasattr(self, "calendar_type_combo"):
                self._select_combo_value(
                    self.calendar_type_combo,
                    self._calendar_type_filter,
                )
            if hasattr(self, "history_search_edit"):
                self.history_search_edit.setText(
                    state.get("history_search_text", "")
                )
            if hasattr(self, "history_type_combo"):
                self._select_combo_value(
                    self.history_type_combo,
                    state.get("history_type_filter", "All Types"),
                )
            if hasattr(self, "history_status_combo"):
                self._select_combo_value(
                    self.history_status_combo,
                    state.get("history_status_filter", "all"),
                )
            if hasattr(self, "history_sort_combo"):
                self._select_combo_value(
                    self.history_sort_combo,
                    state.get("history_sort_filter", "asc"),
                )
        finally:
            for control in controls:
                if control is not None and hasattr(control, "blockSignals"):
                    control.blockSignals(False)

        if self._background_loads_enabled:
            self.request_refresh(force=False)
        else:
            self.load_data()
        self._select_tab(self._selected_tab)

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
