from datetime import date
import time

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services.secretary_work_service import (
    PRIORITIES,
    PROJECT_STATUSES,
    TASK_GROUPS,
    TASK_STATUSES,
    TASK_TYPES,
    TASK_TYPE_LABELS,
    WAITING_REASON_LABELS,
    SecretaryWorkService,
)
from ui.dialogs.office_work_dialogs import ProjectDialog, TaskDialog
from ui.foundation import (
    FilterBar,
    create_button,
    create_card,
    create_combo_box,
    create_pill_action_button,
    create_pill_button,
    create_scroll_area,
    create_search_edit,
    fluent_icon,
    show_message,
)
from utils.constants import DOCUMENTS, WORKFLOW_STAGES
from utils.logger import logger


TASK_GROUP_LABELS = dict(TASK_GROUPS)
TASK_STATUS_LABELS = {
    "OPEN": "To Do",
    "READY": "Ready",
    "WAITING": "Waiting",
    "DONE": "Done",
    "ARCHIVED": "Archived",
}
PROJECT_STATUS_LABELS = {
    "ACTIVE": "Active",
    "WAITING": "Waiting",
    "DONE": "Done",
    "ARCHIVED": "Archived",
}

TASK_BOARD_DRAG_MIME = "application/x-office-work-task"
TASK_BOARD_LANES = ("not_started", "in_progress", "completed")
TASK_BOARD_LANE_LABELS = {
    "not_started": "Not Started",
    "in_progress": "In-Progress",
    "completed": "Completed",
}


def _task_priority_tone(task):
    if task.get("is_group_task"):
        return "group"
    return str(task.get("priority", "LOW")).lower()


def _task_priority_color(task):
    return {
        "normal": "#0EA5AC",
        "important": "#D97706",
        "critical": "#DC2626",
        "group": "#7A6EEC",
    }.get(_task_priority_tone(task), "#71717A")


def _format_date(value):
    if not value:
        return "No due date"
    return value.strftime("%b %d, %Y")


def _due_text(task):
    due_date = task.get("due_date")
    if due_date is None:
        return "No due date"

    days = (due_date - date.today()).days
    if days < 0:
        return f"{abs(days)} day{'s' if abs(days) != 1 else ''} overdue"
    if days == 0:
        return "Due today"
    return f"Due in {days} day{'s' if days != 1 else ''}"


def _transfer_date_from_automation_key(task):
    automation_key = str(task.get("automation_key") or "")
    if not automation_key.startswith("transfer:"):
        return None

    parts = automation_key.split(":")
    if len(parts) < 3:
        return None

    try:
        return date.fromisoformat(parts[-1])
    except ValueError:
        return None


class TaskDropIndicator(QFrame):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = min(24, rect.height() / 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#E5E7EB"))
        painter.drawRoundedRect(rect, radius, radius)


class TaskBoardColumn(QFrame):
    def __init__(self, lane_key, drop_handler, parent=None):
        super().__init__(parent)
        self.lane_key = lane_key
        self._drop_handler = drop_handler
        self.setProperty("dragOver", False)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._drop_indicator = None
        self._drop_indicator_index = None
        self._drop_indicator_animation = None
        self._slide_animation_group = None
        self._drag_snapshot = []

    def _set_drag_over(self, active):
        if self.property("dragOver") == active:
            return
        self.setProperty("dragOver", active)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()

    def _task_widgets(self):
        widgets = []
        layout = self.layout()
        if layout is None:
            return widgets
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None and widget.objectName() == "OfficeWorkTaskPill":
                widgets.append(widget)
        return widgets

    def _insert_layout_widget(self, widget, layout_index):
        layout = self.layout()
        if layout is None:
            return
        layout.insertWidget(layout_index, widget)

    def _clear_drop_indicator(self):
        if self._drop_indicator_animation is not None:
            self._drop_indicator_animation.stop()
            self._drop_indicator_animation.deleteLater()
            self._drop_indicator_animation = None
        if self._slide_animation_group is not None:
            self._slide_animation_group.stop()
            self._slide_animation_group.deleteLater()
            self._slide_animation_group = None
        if self._drop_indicator is None:
            self._drop_indicator_index = None
            return
        layout = self.layout()
        if layout is not None:
            layout.removeWidget(self._drop_indicator)
        self._drop_indicator.deleteLater()
        self._drop_indicator = None
        self._drop_indicator_index = None

    def _capture_drag_snapshot(self):
        self._drag_snapshot = [
            (widget, widget.y() + (widget.height() / 2))
            for widget in self._task_widgets()
        ]

    def _clear_drag_snapshot(self):
        self._drag_snapshot = []

    def _task_card_height(self):
        widgets = self._task_widgets()
        if widgets:
            height = widgets[0].height()
            if height <= 0:
                height = widgets[0].sizeHint().height()
            return max(1, height)
        return 64

    def _show_drop_indicator(self, index):
        layout = self.layout()
        if layout is None:
            return

        index = max(0, min(index, len(self._task_widgets())))
        if self._drop_indicator is not None and self._drop_indicator_index == index:
            return

        old_geometries = {
            widget: widget.geometry()
            for widget in self._task_widgets()
        }
        if self._drop_indicator is None:
            indicator = TaskDropIndicator(self)
            indicator.setObjectName("OfficeWorkTaskDropIndicator")
            indicator.setAttribute(Qt.WA_StyledBackground, True)
            indicator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            indicator.setProperty("visible", True)
            self._drop_indicator = indicator
        else:
            indicator = self._drop_indicator
            layout.removeWidget(indicator)

        indicator.setGraphicsEffect(None)

        target_height = self._task_card_height()
        indicator.setFixedHeight(target_height)
        indicator.setMinimumHeight(target_height)
        indicator.setMaximumHeight(target_height)
        indicator.show()
        self._drop_indicator_index = index

        layout_index = 1 + index
        layout.insertWidget(layout_index, indicator)
        layout.activate()

        animation = QParallelAnimationGroup(self)
        for widget in self._task_widgets():
            old_geometry = old_geometries.get(widget)
            new_geometry = widget.geometry()
            if old_geometry is None or old_geometry == new_geometry:
                continue
            widget_animation = QPropertyAnimation(widget, b"geometry", animation)
            widget_animation.setDuration(260)
            widget_animation.setStartValue(old_geometry)
            widget_animation.setEndValue(new_geometry)
            widget_animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.addAnimation(widget_animation)

        if animation.animationCount():
            animation.start()
            self._slide_animation_group = animation
        else:
            self._slide_animation_group = None

    def _drop_index(self, y):
        snapshot = self._drag_snapshot
        source = snapshot if snapshot else [
            (widget, widget.y() + (widget.height() / 2))
            for widget in self._task_widgets()
        ]
        for index, (_widget, midpoint) in enumerate(source):
            if y < midpoint:
                return index
        return len(source)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(TASK_BOARD_DRAG_MIME):
            self._capture_drag_snapshot()
            self._set_drag_over(True)
            self._show_drop_indicator(
                self._drop_index(event.position().toPoint().y())
            )
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(TASK_BOARD_DRAG_MIME):
            self._set_drag_over(True)
            self._show_drop_indicator(
                self._drop_index(event.position().toPoint().y())
            )
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_over(False)
        self._clear_drop_indicator()
        self._clear_drag_snapshot()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(TASK_BOARD_DRAG_MIME):
            event.ignore()
            return

        try:
            task_id = int(bytes(event.mimeData().data(TASK_BOARD_DRAG_MIME)).decode("utf-8"))
        except Exception:
            event.ignore()
            return

        try:
            self._drop_handler(
                task_id,
                self.lane_key,
                self._drop_index(event.position().toPoint().y()),
            )
            self._set_drag_over(False)
            self._clear_drop_indicator()
            self._clear_drag_snapshot()
            event.acceptProposedAction()
        except Exception:
            self._set_drag_over(False)
            self._clear_drop_indicator()
            self._clear_drag_snapshot()
            event.ignore()


class OfficeWorkPage(QWidget):
    def __init__(self, main_window=None, service=None):
        super().__init__()
        self.setObjectName("OfficeWorkPage")
        self.main_window = main_window
        self.service = service or SecretaryWorkService()
        self._selected_tab = "tasks"
        self._project_filter_id = None
        self._board_lane_orders = {}
        self._board_task_lanes = {}
        self._board_tasks_by_id = {}
        self._projects_loaded = False
        self._last_load_at = 0.0
        self._office_cache_ttl_seconds = 20.0
        self._task_layout_class = None
        self._task_render_timer = QTimer(self)
        self._task_render_timer.setSingleShot(True)
        self._task_render_timer.setInterval(140)
        self._task_render_timer.timeout.connect(self.render_tasks)

        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self.header = self._build_top_bar()
        outer.addWidget(self.header)

        self.stack = QStackedWidget()
        self.stack.setObjectName("OfficeWorkStack")
        self.stack.setMinimumWidth(0)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        workspace = QFrame()
        workspace.setObjectName("OfficeWorkWorkspace")
        workspace.setMinimumWidth(0)
        workspace.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        workspace.setAttribute(Qt.WA_StyledBackground, True)
        workspace_layout = QVBoxLayout()
        workspace_layout.setContentsMargins(12, 12, 24, 24)
        workspace_layout.setSpacing(0)
        workspace.setLayout(workspace_layout)
        workspace_layout.addWidget(self.stack)
        outer.addWidget(workspace, stretch=1)

        self._build_tasks_tab()
        self._build_projects_tab()
        self._select_tab("tasks")

    def _build_top_bar(self):
        frame = QFrame()
        frame.setObjectName("OfficeWorkTopBar")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 12)
        layout.setSpacing(8)
        frame.setLayout(layout)

        top_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_row_layout = top_row
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)

        title = QLabel("Tasks")
        title.setObjectName("OfficeWorkTitle")
        subtitle = QLabel("Track tasks, projects, and follow-up work.")
        subtitle.setObjectName("OfficeWorkSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        top_row.addLayout(title_stack, stretch=1)
        top_row.addWidget(self._build_header_action(), alignment=Qt.AlignRight)
        layout.addLayout(top_row)

        self._build_tabs()
        layout.addWidget(self.tab_bar)
        return frame

    def _build_header_action(self):
        self.add_task_btn = create_button(
            "Add Task",
            "primary",
            icon=fluent_icon("ADD"),
        )
        self.add_task_btn.clicked.connect(self._add_task)
        return self.add_task_btn

    def _build_tabs(self):
        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("OfficeWorkTopTabStrip")
        self.tab_bar.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tab_bar.setLayout(layout)

        self.tab_control = None
        self.tab_buttons = {}
        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        for key, title in [
            ("tasks", "Tasks"),
            ("completed", "Completed"),
            ("projects", "Projects"),
        ]:
            button = QPushButton(title)
            button.setObjectName("OfficeWorkTopTab")
            button.setCheckable(True)
            button.setFixedHeight(30)
            button.clicked.connect(
                lambda checked=False, route_key=key:
                self._select_tab(route_key)
            )
            self.tab_button_group.addButton(button)
            self.tab_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch()

    def _build_tasks_tab(self):
        tab = QWidget()
        tab.setObjectName("PageSurface")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tab.setLayout(layout)

        self._build_task_filters()
        layout.addWidget(self.task_filter_bar)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")
        content = QWidget()
        content.setObjectName("PageSurface")
        self.task_content_layout = QVBoxLayout()
        self.task_content_layout.setContentsMargins(20, 18, 20, 20)
        self.task_content_layout.setSpacing(16)
        content.setLayout(self.task_content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)
        self.tasks_index = self.stack.addWidget(tab)

    def _build_projects_tab(self):
        tab = QWidget()
        tab.setObjectName("PageSurface")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tab.setLayout(layout)

        self._build_project_filters()
        layout.addWidget(self.project_filter_bar)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")
        content = QWidget()
        content.setObjectName("PageSurface")
        self.project_content_layout = QVBoxLayout()
        self.project_content_layout.setContentsMargins(20, 18, 20, 20)
        self.project_content_layout.setSpacing(16)
        content.setLayout(self.project_content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)
        self.projects_index = self.stack.addWidget(tab)

    def _build_task_filters(self):
        self.task_filter_bar = FilterBar()
        self.task_filter_bar.setObjectName("OfficeWorkFilterBar")

        self.task_search = create_search_edit("Search tasks")
        self.task_search.textChanged.connect(self._schedule_task_render)
        self.task_filter_bar.add_filter(self.task_search, stretch=1)

        self.task_filter_button = create_pill_button("Filters")
        self.task_filter_button.setObjectName("OfficeWorkTaskFilterMenuButton")
        self.task_filter_button.clicked.connect(self._show_task_filter_menu)
        self.task_filter_bar.add_filter(self.task_filter_button)

        self.task_status_filter = create_combo_box()
        self.task_status_filter.addItem("Visible", None)
        self.task_status_filter.addItem("All", "ALL")
        for status in TASK_STATUSES:
            self.task_status_filter.addItem(
                TASK_STATUS_LABELS.get(status, status.title()),
                status,
            )
        self.task_status_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_priority_filter = create_combo_box()
        self.task_priority_filter.addItem("All Priorities", "ALL")
        for priority in PRIORITIES:
            self.task_priority_filter.addItem(priority.title(), priority)
        self.task_priority_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_type_filter = create_combo_box()
        self.task_type_filter.addItem("All Types", "ALL")
        for task_type in TASK_TYPES:
            self.task_type_filter.addItem(
                TASK_TYPE_LABELS.get(task_type, task_type.title()),
                task_type,
            )
        self.task_type_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_stage_filter = create_combo_box()
        self.task_stage_filter.addItem("All Stages", "ALL")
        for stage in WORKFLOW_STAGES:
            self.task_stage_filter.addItem(stage.title(), stage)
        self.task_stage_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_document_filter = create_combo_box()
        self.task_document_filter.addItem("All Documents", "ALL")
        for document_type, definition in sorted(
            DOCUMENTS.items(),
            key=lambda item: item[1].get("label", item[0]).casefold(),
        ):
            self.task_document_filter.addItem(
                definition.get("label", document_type),
                document_type,
            )
        self.task_document_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_source_filter = create_combo_box()
        self.task_source_filter.addItem("All Sources", "ALL")
        self.task_source_filter.addItem("Manual", "MANUAL")
        self.task_source_filter.addItem("Auto", "AUTO")
        self.task_source_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_due_filter = create_combo_box()
        for label, value in [
            ("All Due Dates", "all"),
            ("Overdue", "overdue"),
            ("Today", "today"),
            ("This Week", "this_week"),
            ("Later", "later"),
            ("No Due Date", "no_due_date"),
        ]:
            self.task_due_filter.addItem(label, value)
        self.task_due_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_follow_up_filter = create_combo_box()
        self.task_follow_up_filter.addItem("All Follow-Ups", "ALL")
        self.task_follow_up_filter.addItem("Follow Up Due", "due")
        self.task_follow_up_filter.addItem("Upcoming Follow-Ups", "upcoming")
        self.task_follow_up_filter.addItem("No Follow-Up", "missing")
        self.task_follow_up_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_waiting_reason_filter = create_combo_box()
        self.task_waiting_reason_filter.addItem("All Waiting Reasons", "ALL")
        for reason, label in WAITING_REASON_LABELS.items():
            self.task_waiting_reason_filter.addItem(label, reason)
        self.task_waiting_reason_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )

        self.task_project_filter = create_combo_box()
        self.task_project_filter.currentIndexChanged.connect(
            lambda _=None: self._project_filter_changed()
        )

        self.task_missionary_filter = create_combo_box()
        self.task_missionary_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )
        self.task_filter_menu = None

    def _show_task_filter_menu(self):
        menu = QMenu(self)
        menu.setObjectName("WorkspaceTileContextMenu")

        quick_filters = menu.addMenu("Quick Filters")
        quick_filters.setObjectName("WorkspaceTileContextMenu")
        for label, preset in [
            ("Today", "today"),
            ("Overdue", "overdue"),
            ("Follow Up", "follow_up"),
            ("Waiting", "waiting"),
            ("Ready", "ready"),
            ("Appointments", "appointments"),
            ("Critical", "critical"),
            ("All", "all"),
        ]:
            action = quick_filters.addAction(label)
            action.triggered.connect(
                lambda checked=False, preset_key=preset:
                self._apply_task_preset(preset_key)
            )

        menu.addSeparator()
        self._add_filter_menu_group(menu, "Status", self.task_status_filter)
        self._add_filter_menu_group(menu, "Priority", self.task_priority_filter)
        self._add_filter_menu_group(menu, "Type", self.task_type_filter)
        self._add_filter_menu_group(menu, "Stage", self.task_stage_filter)
        self._add_filter_menu_group(menu, "Document", self.task_document_filter)
        self._add_filter_menu_group(menu, "Source", self.task_source_filter)
        self._add_filter_menu_group(menu, "Due", self.task_due_filter)
        self._add_filter_menu_group(menu, "Follow-Up", self.task_follow_up_filter)
        self._add_filter_menu_group(
            menu, "Waiting Reason", self.task_waiting_reason_filter
        )
        self._add_filter_menu_group(menu, "Project", self.task_project_filter)
        self._add_filter_menu_group(menu, "Missionary", self.task_missionary_filter)

        self.task_filter_menu = menu
        menu.popup(self.task_filter_button.mapToGlobal(self.task_filter_button.rect().bottomLeft()))

    def _add_filter_menu_group(self, menu, title, combo):
        submenu = menu.addMenu(title)
        submenu.setObjectName("WorkspaceTileContextMenu")
        current_value = combo.currentData()
        for index in range(combo.count()):
            label = combo.itemText(index)
            value = combo.itemData(index)
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current_value)
            action.triggered.connect(
                lambda checked=False, widget=combo, selected=value:
                self._set_combo_data(widget, selected)
            )

    def _build_project_filters(self):
        self.project_filter_bar = FilterBar()
        self.project_filter_bar.setObjectName("OfficeWorkFilterBar")

        self.project_search = create_search_edit("Search projects")
        self.project_search.textChanged.connect(self.render_projects)
        self.project_filter_bar.add_filter(self.project_search, stretch=1)

        self.project_status_filter = create_combo_box()
        self.project_status_filter.addItem("Visible", None)
        self.project_status_filter.addItem("All", "ALL")
        for status in PROJECT_STATUSES:
            self.project_status_filter.addItem(
                PROJECT_STATUS_LABELS.get(status, status.title()),
                status,
            )
        self.project_status_filter.currentIndexChanged.connect(
            lambda _=None: self.render_projects()
        )
        self.project_filter_bar.add_filter(self.project_status_filter)

        self.project_priority_filter = create_combo_box()
        self.project_priority_filter.addItem("All Priorities", "ALL")
        for priority in PRIORITIES:
            self.project_priority_filter.addItem(priority.title(), priority)
        self.project_priority_filter.currentIndexChanged.connect(
            lambda _=None: self.render_projects()
        )
        self.project_filter_bar.add_filter(self.project_priority_filter)

        add_project_btn = create_button("Add Project", "primary")
        add_project_btn.clicked.connect(self._add_project)
        self.project_filter_bar.add_filter(add_project_btn)

    def load_data(self):
        """Force a refresh after task or project mutations."""
        self._run_process_automation()
        self._refresh_task_filter_options()
        self.render_tasks()
        if self._selected_tab == "projects":
            self.render_projects()
        else:
            self._projects_loaded = False
        self._last_load_at = time.monotonic()

    def request_refresh(self):
        """Refresh navigation only when the Office Work cache is stale."""
        if time.monotonic() - self._last_load_at < self._office_cache_ttl_seconds:
            return False
        self.load_data()
        return True

    def _schedule_task_render(self, *_args):
        self._task_render_timer.start()

    @staticmethod
    def _task_layout_class_for_width(width):
        return "stacked" if width < 1100 else "wide"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        layout_class = self._task_layout_class_for_width(event.size().width())
        if layout_class == self._task_layout_class:
            return
        self._task_layout_class = layout_class
        if hasattr(self, "top_row_layout"):
            self.top_row_layout.setDirection(
                QBoxLayout.TopToBottom
                if layout_class == "stacked"
                else QBoxLayout.LeftToRight
            )
        if hasattr(self, "task_content_layout"):
            self._schedule_task_render()

    def _run_process_automation(self):
        if not self.main_window:
            return
        try:
            from services.process_automation_service import (
                ProcessAutomationService,
            )

            ProcessAutomationService(
                settings_service=self.main_window.settings_service
            ).run()
        except Exception:
            logger.exception("Process automation failed during office work load")

    def _refresh_task_filter_options(self):
        current_project = self._project_filter_id
        current_missionary = self.task_missionary_filter.currentData() if hasattr(
            self,
            "task_missionary_filter",
        ) else None

        self.task_project_filter.blockSignals(True)
        self.task_project_filter.clear()
        self.task_project_filter.addItem("All Projects", None)
        for project in self.service.project_options():
            self.task_project_filter.addItem(project["title"], project["id"])
        self._set_combo_data(self.task_project_filter, current_project)
        self.task_project_filter.blockSignals(False)

        self.task_missionary_filter.blockSignals(True)
        self.task_missionary_filter.clear()
        self.task_missionary_filter.addItem("All Missionaries", None)
        for missionary in self.service.missionary_options():
            self.task_missionary_filter.addItem(missionary["name"], missionary["id"])
        self._set_combo_data(self.task_missionary_filter, current_missionary)
        self.task_missionary_filter.blockSignals(False)

    def render_tasks(self):
        if not hasattr(self, "task_content_layout"):
            return

        self._clear_layout(self.task_content_layout)

        completed_tab = self._selected_tab == "completed"
        grouped = self.service.grouped_tasks(
            search=self.task_search.text(),
            status="DONE" if completed_tab else self.task_status_filter.currentData(),
            priority=self.task_priority_filter.currentData(),
            project_id=self._project_filter_id,
            missionary_id=self.task_missionary_filter.currentData(),
            due_range=self.task_due_filter.currentData(),
            task_type=self.task_type_filter.currentData(),
            related_stage=self.task_stage_filter.currentData(),
            related_document_type=self.task_document_filter.currentData(),
            automation_state=self.task_source_filter.currentData(),
            waiting_follow_up=self.task_follow_up_filter.currentData(),
            waiting_reason=self.task_waiting_reason_filter.currentData(),
            include_done=completed_tab,
        )

        board_groups = self._task_board_groups(grouped)
        if not any(board_groups.values()):
            self.task_content_layout.addWidget(
                self._empty_state(
                    "No completed tasks match the current filters."
                    if completed_tab
                    else "No tasks match the current filters."
                )
            )
        else:
            self.task_content_layout.addWidget(self._task_board(board_groups))

        self.task_content_layout.addStretch()

    def _task_board_groups(self, grouped):
        columns = {"not_started": [], "in_progress": [], "completed": []}
        seen_ids = set()

        for group_key, _label in TASK_GROUPS:
            for task in grouped.get(group_key, []):
                task_id = task.get("id")
                if task_id in seen_ids:
                    continue
                columns[self._task_board_column_key(task)].append(task)
                seen_ids.add(task_id)

        for lane in TASK_BOARD_LANES:
            columns[lane] = sorted(
                columns[lane],
                key=self._task_board_sort_key,
            )

        self._board_lane_orders = {
            lane: [task["id"] for task in tasks]
            for lane, tasks in columns.items()
        }
        self._board_task_lanes = {
            task["id"]: lane
            for lane, tasks in columns.items()
            for task in tasks
        }
        self._board_tasks_by_id = {
            task["id"]: task
            for tasks in columns.values()
            for task in tasks
        }
        return columns

    def _task_board_column_key(self, task):
        saved_lane = str(task.get("board_lane") or "").strip()
        if saved_lane in TASK_BOARD_LANES:
            return saved_lane

        status = task.get("status")
        if status in {"DONE", "ARCHIVED"}:
            return "completed"
        if status in {"READY", "WAITING"} or task.get("due_group") in {
            "follow_up_due",
            "needs_follow_up",
            "scheduled_follow_up",
            "ready_to_review",
        }:
            return "in_progress"
        return "not_started"

    @staticmethod
    def _task_board_sort_key(task):
        board_position = task.get("board_position")
        return (
            board_position is None,
            board_position if board_position is not None else 0,
            task.get("due_date") or date.max,
            task.get("title", "").casefold(),
            task.get("id") or 0,
        )

    def _task_board(self, board_groups):
        board = QWidget()
        board.setObjectName("OfficeWorkTaskBoard")
        board.setMinimumWidth(0)
        board.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        board_layout = QBoxLayout(
            QBoxLayout.LeftToRight
            if self._task_layout_class_for_width(self.width()) == "wide"
            else QBoxLayout.TopToBottom
        )
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(12)
        board.setLayout(board_layout)
        lanes = (
            (("completed", TASK_BOARD_LANE_LABELS["completed"]),)
            if self._selected_tab == "completed"
            else (
                ("not_started", TASK_BOARD_LANE_LABELS["not_started"]),
                ("in_progress", TASK_BOARD_LANE_LABELS["in_progress"]),
            )
        )
        for key, label in lanes:
            board_layout.addWidget(
                self._task_board_column(key, label, board_groups.get(key, []))
            )

        return board

    def _task_board_column(self, lane_key, label, tasks):
        column = TaskBoardColumn(lane_key, self._handle_task_board_drop)
        column.setObjectName("OfficeWorkTaskColumn")
        column.setMinimumWidth(0)
        column.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        column_layout = QVBoxLayout()
        column_layout.setContentsMargins(10, 10, 10, 10)
        column_layout.setSpacing(8)
        column.setLayout(column_layout)

        column_layout.addWidget(self._section_header(label, len(tasks)))
        if tasks:
            for task in tasks:
                column_layout.addWidget(self._task_row(task))
        else:
            empty = QLabel("No tasks")
            empty.setObjectName("OfficeWorkColumnEmpty")
            column_layout.addWidget(empty)
        column_layout.addStretch()
        return column

    def render_projects(self):
        if not hasattr(self, "project_content_layout"):
            return

        self._clear_layout(self.project_content_layout)

        projects = self.service.list_projects(
            search=self.project_search.text(),
            status=self.project_status_filter.currentData(),
            priority=self.project_priority_filter.currentData(),
            include_done=self.project_status_filter.currentData() == "ALL",
        )
        if not projects:
            self.project_content_layout.addWidget(
                self._empty_state("No projects match the current filters.")
            )
        else:
            for project in projects:
                self.project_content_layout.addWidget(self._project_row(project))

        self.project_content_layout.addStretch()
        self._projects_loaded = True

    def _task_row(self, task):
        meta_parts = [_due_text(task)]
        meta_parts.append(TASK_STATUS_LABELS.get(task["status"], task["status"].title()))
        scope_label = task.get("scope_label") or task.get("missionary_name")
        if scope_label:
            meta_parts.append(scope_label)

        doc_stage_parts = []
        if task.get("related_document_label"):
            doc_stage_parts.append(task["related_document_label"])
        if task.get("related_stage"):
            doc_stage_parts.append(task["related_stage"].title())
        if doc_stage_parts:
            meta_parts.append(" / ".join(doc_stage_parts))

        menu_actions = [
            {
                "text": "Review",
                "tooltip": "Review task",
                "icon": "panel-top-open",
                "fallback": "...",
                "callback": lambda task_id=task["id"]: self._open_task_workspace(task_id),
            }
        ]
        visible_actions = []

        if task["status"] not in {"DONE", "ARCHIVED"}:
            if task["status"] == "READY":
                menu_actions.append(
                    {
                        "text": "Needs Work",
                        "tooltip": "Mark needs work",
                        "icon": "rotate-ccw",
                        "fallback": "!",
                        "callback": lambda task_id=task["id"]: self._reopen_task(task_id),
                    }
                )
            else:
                if (
                    task["status"] == "WAITING"
                    and task.get("waiting_follow_up_date") is None
                ):
                    menu_actions.append(
                        {
                            "text": "Set Follow-Up",
                            "tooltip": "Set follow-up",
                            "icon": "calendar-plus",
                            "fallback": "+",
                            "callback": lambda item=task: self._edit_task(item),
                        }
                    )

            visible_actions.append(
                {
                    "text": "",
                    "tooltip": "Mark complete",
                    "icon": "check",
                    "fallback": "",
                    "callback": lambda task_id=task["id"]: self._complete_task(task_id),
                }
            )

        menu_actions.append(
            {
                "text": "Edit",
                "tooltip": "Edit task",
                "icon": "pencil",
                "fallback": "E",
                "callback": lambda item=task: self._edit_task(item),
            }
        )

        if task["status"] != "ARCHIVED":
            menu_actions.append(
                {
                    "text": "Archive",
                    "tooltip": "Archive task",
                    "icon": "archive",
                    "fallback": "A",
                    "callback": lambda task_id=task["id"]: self._archive_task(task_id),
                }
            )

        if task.get("missionary_count", 0) > 1:
            menu_actions.append(
                {
                    "text": "Missionaries",
                    "tooltip": "Show linked missionaries",
                    "icon": "users",
                    "fallback": "M",
                    "callback": lambda item=task: self._show_linked_missionaries(item),
                }
            )
        elif task.get("missionary_id"):
            menu_actions.append(
                {
                    "text": "Open Missionary",
                    "tooltip": "Open missionary",
                    "icon": "external-link",
                    "fallback": ">",
                    "callback": lambda missionary_id=task["missionary_id"]:
                    self._open_missionary(missionary_id),
                }
            )

        if task["status"] != "ARCHIVED":
            menu_actions.append(
                {
                    "text": "Delete",
                    "tooltip": "Delete task",
                    "icon": "x",
                    "fallback": "x",
                    "callback": lambda task_id=task["id"]: self._delete_task(task_id),
                }
            )

        actions = [
            {
                "text": "More",
                "tooltip": "More actions",
                "icon": "ellipsis-vertical",
                "fallback_icons": ["more-vertical"],
                "fallback": "...",
                "menu": menu_actions,
            },
            *visible_actions,
        ]

        card = create_pill_action_button(
            task["title"],
            subtitle="  |  ".join(meta_parts),
            actions=actions,
            accent=_task_priority_color(task),
            leading_icon=(
                ("triangle-alert", "alert-triangle")
                if task.get("due_group") == "overdue"
                else None
            ),
            leading_icon_color="#DC2626",
            drag_payload=task["id"],
            drag_mime_type=TASK_BOARD_DRAG_MIME,
            drag_preview_widget=None,
            object_name="OfficeWorkTaskPill",
        )
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        card.setProperty("compactLayout", True)
        card.label.setMinimumWidth(0)
        card.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        card.subtitle.setMinimumWidth(0)
        card.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        card.layout().setContentsMargins(10, 6, 8, 6)
        card.layout().setSpacing(6)
        card.clicked.connect(
            lambda task_id=task["id"]: self._open_task_workspace(task_id)
        )
        return card

    def _handle_task_board_drop(self, task_id, target_lane, target_index):
        source_lane = self._board_task_lanes.get(task_id)
        if source_lane is None:
            snapshot = self._task_snapshot_by_id(task_id) or {}
            source_lane = self._task_board_column_key(snapshot)

        if source_lane not in TASK_BOARD_LANES:
            source_lane = "not_started"

        source_order = list(self._board_lane_orders.get(source_lane, []))
        target_order = list(self._board_lane_orders.get(target_lane, []))

        if task_id in source_order:
            source_index = source_order.index(task_id)
            source_order.remove(task_id)
        else:
            source_index = None

        if target_lane == source_lane and task_id in target_order:
            target_order.remove(task_id)
            if source_index is not None and target_index > source_index:
                target_index -= 1
        elif task_id in target_order:
            target_order.remove(task_id)

        target_index = max(0, min(target_index, len(target_order)))
        target_order.insert(target_index, task_id)

        lane_orders = {}
        if source_lane == target_lane:
            lane_orders[target_lane] = target_order
        else:
            lane_orders[source_lane] = source_order
            lane_orders[target_lane] = target_order

        try:
            self.service.save_task_board_orders(lane_orders)
            self.render_tasks()
        except Exception:
            logger.exception("Failed to move office work task on board")
            show_message(
                self,
                "Office Work",
                "Could not save the board move.",
                kind="warning",
            )

    def _task_snapshot_by_id(self, task_id):
        return self._board_tasks_by_id.get(task_id)

    def _project_row(self, project):
        card = create_card(object_name="OfficeWorkRow")
        layout = QBoxLayout(
            QBoxLayout.TopToBottom
            if self._task_layout_class_for_width(self.width()) == "stacked"
            else QBoxLayout.LeftToRight
        )
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        card.setLayout(layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(4)
        title = QLabel(project["title"])
        title.setObjectName("StrongText")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_stack.addWidget(title)

        task_breakdown = self._project_task_breakdown(project)
        meta = QLabel(
            "  |  ".join([
                project["priority"].title(),
                PROJECT_STATUS_LABELS.get(project["status"], project["status"].title()),
                _format_date(project.get("due_date")),
                project["progress"],
                task_breakdown,
            ])
        )
        meta.setObjectName("OfficeWorkMeta")
        meta.setWordWrap(True)
        meta.setMinimumWidth(0)
        meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_stack.addWidget(meta)
        layout.addLayout(text_stack, stretch=1)

        tasks_btn = create_button("View Tasks", "secondary", fixed_height=28)
        tasks_btn.clicked.connect(
            lambda _=None, project_id=project["id"]:
            self._show_project_tasks(project_id)
        )
        layout.addWidget(tasks_btn)

        add_task_btn = create_button("Add Task", "primary", fixed_height=28)
        add_task_btn.clicked.connect(
            lambda _=None, project_id=project["id"]:
            self._add_task(project_id=project_id)
        )
        layout.addWidget(add_task_btn)

        edit_btn = create_button("Edit", "secondary", fixed_height=28)
        edit_btn.clicked.connect(lambda _=None, item=project: self._edit_project(item))
        layout.addWidget(edit_btn)

        if project["status"] not in {"DONE", "ARCHIVED"}:
            done_btn = create_button("Done", "success", fixed_height=28)
            done_btn.clicked.connect(
                lambda _=None, project_id=project["id"]:
                self._complete_project(project_id)
            )
            layout.addWidget(done_btn)

        if project["status"] != "ARCHIVED":
            archive_btn = create_button("Archive", "subtle", fixed_height=28)
            archive_btn.clicked.connect(
                lambda _=None, project_id=project["id"]:
                self._archive_project(project_id)
            )
            layout.addWidget(archive_btn)

        return card

    @staticmethod
    def _project_task_breakdown(project):
        parts = []
        for key, label in [
            ("todo_tasks", "to do"),
            ("ready_tasks", "ready"),
            ("waiting_tasks", "waiting"),
        ]:
            count = project.get(key, 0)
            if count:
                parts.append(f"{count} {label}")
        if parts:
            return ", ".join(parts)
        return f"{project.get('open_tasks', 0)} open"

    def _section_header(self, title, count):
        row = QFrame()
        row.setObjectName("OfficeWorkSectionHeader")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 12, 0, 0)
        row.setLayout(layout)

        label = QLabel(title)
        label.setObjectName("OfficeWorkSectionTitle")
        layout.addWidget(label)
        count_label = QLabel(str(count))
        count_label.setObjectName("OfficeWorkSectionCount")
        layout.addWidget(count_label)
        layout.addStretch()
        return row

    def _empty_state(self, message):
        card = create_card()
        card.setObjectName("OfficeWorkEmptyState")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(6)
        card.setLayout(layout)
        label = QLabel(message)
        label.setObjectName("PanelTitle")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        return card

    def _select_tab(self, key):
        if key == "projects":
            self.stack.setCurrentIndex(self.projects_index)
            if not self._projects_loaded:
                self.render_projects()
        else:
            key = "completed" if key == "completed" else "tasks"
            self.stack.setCurrentIndex(self.tasks_index)

        self._selected_tab = key
        if key in {"tasks", "completed"}:
            self.render_tasks()
        if self.tab_control is not None:
            current_key = getattr(self.tab_control, "currentRouteKey", lambda: None)()
            if current_key != key:
                self.tab_control.setCurrentItem(key)
        elif key in self.tab_buttons:
            self.tab_buttons[key].setChecked(True)
        self._refresh_tab_buttons()

    def _refresh_tab_buttons(self):
        for tab_key, button in self.tab_buttons.items():
            button.setProperty("active", tab_key == self._selected_tab)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_project_tasks(self, project_id):
        self._project_filter_id = project_id
        self._set_combo_data(self.task_project_filter, project_id)
        self._select_tab("tasks")
        self.render_tasks()

    def _project_filter_changed(self):
        self._project_filter_id = self.task_project_filter.currentData()
        self.render_tasks()

    def _apply_task_preset(self, preset):
        self.task_search.clear()
        self._project_filter_id = None
        self._set_combo_data(self.task_project_filter, None)
        self._set_combo_data(self.task_missionary_filter, None)
        self._set_combo_data(self.task_status_filter, None)
        self._set_combo_data(self.task_priority_filter, "ALL")
        self._set_combo_data(self.task_type_filter, "ALL")
        self._set_combo_data(self.task_stage_filter, "ALL")
        self._set_combo_data(self.task_document_filter, "ALL")
        self._set_combo_data(self.task_source_filter, "ALL")
        self._set_combo_data(self.task_due_filter, "all")
        self._set_combo_data(self.task_follow_up_filter, "ALL")
        self._set_combo_data(self.task_waiting_reason_filter, "ALL")

        if preset == "open":
            self._set_combo_data(self.task_status_filter, "OPEN")
        elif preset in {"today", "due_today"}:
            self._set_combo_data(self.task_due_filter, "today")
        elif preset == "overdue":
            self._set_combo_data(self.task_due_filter, "overdue")
        elif preset == "follow_up":
            self._set_combo_data(self.task_follow_up_filter, "due")
        elif preset == "upcoming_follow_up":
            self._set_combo_data(self.task_follow_up_filter, "upcoming")
        elif preset == "missing_follow_up":
            self._set_combo_data(self.task_follow_up_filter, "missing")
        elif preset == "waiting":
            self._set_combo_data(self.task_status_filter, "WAITING")
        elif preset == "ready":
            self._set_combo_data(self.task_status_filter, "READY")
        elif preset == "appointments":
            self._set_combo_data(self.task_type_filter, "APPOINTMENT")
        elif preset == "critical":
            self._set_combo_data(self.task_priority_filter, "CRITICAL")
        elif preset == "all":
            pass
        self.render_tasks()

    def focus_task_context(self, task_id=None, title=""):
        if task_id is not None:
            self._open_task_workspace(task_id)
            return
        self._select_tab("tasks")
        if hasattr(self, "task_status_filter"):
            self._set_combo_data(self.task_status_filter, None)
        if hasattr(self, "task_search"):
            self.task_search.setText(title or "")
        self.render_tasks()

    def _add_task(self, project_id=None, missionary_id=None):
        defaults = {}
        if project_id is not None:
            defaults["project_id"] = project_id
        if missionary_id is not None:
            defaults["missionary_id"] = missionary_id
        dialog = TaskDialog(
            self.service,
            defaults=defaults or None,
            parent=self,
        )
        if dialog.exec():
            self.load_data()
            self._refresh_calendar_page()

    def _edit_task(self, task):
        dialog = TaskDialog(self.service, task=task, parent=self)
        if dialog.exec():
            self.load_data()
            self._refresh_calendar_page()

    def _task_row_clicked(self, event, task_id):
        if event.button() == Qt.LeftButton:
            self._open_task_workspace(task_id)
            event.accept()
            return
        event.ignore()

    def _open_task_workspace(self, task_id):
        if self.main_window is not None:
            opener = getattr(self.main_window, "open_alert_workspace", None)
            if callable(opener):
                opener(task_id, return_key="office_work")
                return
        self.focus_task_context(title="")

    def _add_project(self):
        dialog = ProjectDialog(self.service, parent=self)
        if dialog.exec():
            self.load_data()

    def _edit_project(self, project):
        dialog = ProjectDialog(self.service, project=project, parent=self)
        if dialog.exec():
            self.load_data()

    def _complete_task(self, task_id):
        self.service.complete_task(task_id)
        self.load_data()
        self._refresh_calendar_page()

    def _mark_task_ready(self, task_id):
        self.service.mark_task_ready(task_id)
        self.load_data()
        self._refresh_calendar_page()

    def _reopen_task(self, task_id):
        self.service.reopen_task(task_id)
        self.load_data()
        self._refresh_calendar_page()

    def _archive_task(self, task_id):
        self.service.archive_task(task_id)
        self.load_data()
        self._refresh_calendar_page()

    def _delete_task(self, task_id):
        response = show_message(
            self,
            "Delete Task",
            "Permanently delete this task?\n\nThis cannot be undone.",
            kind="question",
            buttons="yes_no",
        )
        if response not in {1, 16384}:
            return
        self.service.delete_task(task_id)
        self.load_data()
        self._refresh_calendar_page()

    def _show_linked_missionaries(self, task):
        names = task.get("missionary_names") or []
        if not names:
            show_message(
                self,
                "Linked Missionaries",
                "No missionaries are linked to this task.",
            )
            return
        show_message(
            self,
            "Linked Missionaries",
            "\n".join(names),
        )

    def _complete_project(self, project_id):
        self.service.complete_project(project_id)
        self.load_data()

    def _archive_project(self, project_id):
        self.service.archive_project(project_id)
        self.load_data()

    def _refresh_calendar_page(self):
        calendar_page = getattr(self.main_window, "calendar_page", None)
        if calendar_page is not None and hasattr(calendar_page, "load_data"):
            calendar_page.load_data()

    def _open_missionary(self, missionary_id):
        if not self.main_window:
            return

        opener = getattr(
            self.main_window,
            "open_missionary_detail",
            None,
        )
        if callable(opener):
            opener(missionary_id)

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            widget = item.widget()
            if child_layout is not None:
                self._clear_layout(child_layout)
            if widget is not None:
                widget.deleteLater()
