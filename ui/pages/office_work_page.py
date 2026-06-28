from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from database.db import SessionLocal
from database.models.missionary import Missionary
from services.secretary_work_service import (
    PRIORITIES,
    PROJECT_STATUSES,
    TASK_GROUPS,
    TASK_STATUSES,
    SecretaryWorkService,
)
from ui.dialogs.office_work_dialogs import ProjectDialog, TaskDialog
from ui.foundation import (
    FilterBar,
    StatCard,
    create_button,
    create_card,
    create_combo_box,
    create_scroll_area,
    create_search_edit,
    fluent_icon,
    show_message,
)
from utils.logger import logger


TASK_GROUP_LABELS = dict(TASK_GROUPS)
TASK_STATUS_LABELS = {
    "OPEN": "To Do",
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


def _task_priority_tone(task):
    if task.get("is_group_task"):
        return "group"
    return str(task.get("priority", "LOW")).lower()


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


class OfficeWorkPage(QWidget):
    def __init__(self, main_window=None, service=None):
        super().__init__()
        self.setObjectName("OfficeWorkPage")
        self.main_window = main_window
        self.service = service or SecretaryWorkService()
        self._selected_tab = "tasks"
        self._project_filter_id = None

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

        workspace = QFrame()
        workspace.setObjectName("OfficeWorkWorkspace")
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

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)

        title = QLabel("Office Work")
        title.setObjectName("OfficeWorkTitle")
        subtitle = QLabel("Track secretary tasks, projects, and follow-up work.")
        subtitle.setObjectName("OfficeWorkSubtitle")
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
        for key, title in [("tasks", "Tasks"), ("projects", "Projects")]:
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
        self.task_search.textChanged.connect(self.render_tasks)
        self.task_filter_bar.add_filter(self.task_search, stretch=1)

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
        self.task_filter_bar.add_filter(self.task_status_filter)

        self.task_priority_filter = create_combo_box()
        self.task_priority_filter.addItem("All Priorities", "ALL")
        for priority in PRIORITIES:
            self.task_priority_filter.addItem(priority.title(), priority)
        self.task_priority_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )
        self.task_filter_bar.add_filter(self.task_priority_filter)

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
        self.task_filter_bar.add_filter(self.task_due_filter)

        self.task_project_filter = create_combo_box()
        self.task_project_filter.currentIndexChanged.connect(
            lambda _=None: self._project_filter_changed()
        )
        self.task_filter_bar.add_filter(self.task_project_filter)

        self.task_missionary_filter = create_combo_box()
        self.task_missionary_filter.currentIndexChanged.connect(
            lambda _=None: self.render_tasks()
        )
        self.task_filter_bar.add_filter(self.task_missionary_filter)

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
        self._run_process_automation()
        self._refresh_task_filter_options()
        self.render_tasks()
        self.render_projects()

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
        self._build_summary_cards()

        grouped = self.service.grouped_tasks(
            search=self.task_search.text(),
            status=self.task_status_filter.currentData(),
            priority=self.task_priority_filter.currentData(),
            project_id=self._project_filter_id,
            missionary_id=self.task_missionary_filter.currentData(),
            due_range=self.task_due_filter.currentData(),
            include_done=self.task_status_filter.currentData() == "ALL",
        )

        has_tasks = False
        for group_key, label in TASK_GROUPS:
            tasks = grouped.get(group_key, [])
            if not tasks:
                continue
            has_tasks = True
            self.task_content_layout.addWidget(
                self._section_header(label, len(tasks))
            )
            for task in tasks:
                self.task_content_layout.addWidget(self._task_row(task))

        if not has_tasks:
            self.task_content_layout.addWidget(
                self._empty_state("No tasks match the current filters.")
            )

        self.task_content_layout.addStretch()

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

    def _build_summary_cards(self):
        summary = self.service.summary()
        row = QHBoxLayout()
        row.setSpacing(10)
        for key, label, color in [
            ("open", "To Do", "#0EA5AC"),
            ("overdue", "Overdue", "#DC2626"),
            ("due_today", "Due Today", "#D97706"),
            ("waiting", "Waiting", "#71717A"),
        ]:
            row.addWidget(StatCard(summary.get(key, 0), label, color=color))

        wrapper = QWidget()
        wrapper.setObjectName("OfficeWorkSummaryRow")
        wrapper.setLayout(row)
        self.task_content_layout.addWidget(wrapper)

    def _task_row(self, task):
        card = create_card(object_name="OfficeWorkRow")
        card.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        card.setLayout(layout)

        accent = QFrame()
        accent.setObjectName("OfficeWorkPriorityAccent")
        accent.setFixedWidth(4)
        accent.setProperty("tone", _task_priority_tone(task))
        layout.addWidget(accent)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(4)
        title = QLabel(task["title"])
        title.setObjectName("StrongText")
        text_stack.addWidget(title)

        meta_parts = [
            task["priority"].title(),
            _due_text(task),
            TASK_STATUS_LABELS.get(task["status"], task["status"].title()),
        ]
        if task.get("waiting_reason_label"):
            meta_parts.append(task["waiting_reason_label"])
        if task.get("project_title"):
            meta_parts.append(task["project_title"])
        if task.get("scope_label"):
            meta_parts.append(task["scope_label"])
        elif task.get("missionary_name"):
            meta_parts.append(task["missionary_name"])
        meta = QLabel("  |  ".join(meta_parts))
        meta.setObjectName("OfficeWorkMeta")
        text_stack.addWidget(meta)
        layout.addLayout(text_stack, stretch=1)

        review_btn = create_button("Review", "primary", fixed_height=28)
        review_btn.clicked.connect(
            lambda _=None, task_id=task["id"]:
            self._open_task_workspace(task_id)
        )
        layout.addWidget(review_btn)

        if task["status"] not in {"DONE", "ARCHIVED"}:
            done_btn = create_button("Done", "success", fixed_height=28)
            done_btn.clicked.connect(lambda _=None, task_id=task["id"]: self._complete_task(task_id))
            layout.addWidget(done_btn)

        edit_btn = create_button("Edit", "secondary", fixed_height=28)
        edit_btn.clicked.connect(lambda _=None, item=task: self._edit_task(item))
        layout.addWidget(edit_btn)

        if task["status"] != "ARCHIVED":
            archive_btn = create_button("Archive", "subtle", fixed_height=28)
            archive_btn.clicked.connect(
                lambda _=None, task_id=task["id"]: self._archive_task(task_id)
            )
            layout.addWidget(archive_btn)

        delete_btn = create_button("Delete", "danger", fixed_height=28)
        delete_btn.clicked.connect(
            lambda _=None, task_id=task["id"]: self._delete_task(task_id)
        )
        layout.addWidget(delete_btn)

        if task.get("missionary_count", 0) > 1:
            scope_btn = create_button("Missionaries", "subtle", fixed_height=28)
            scope_btn.clicked.connect(
                lambda _=None, item=task: self._show_linked_missionaries(item)
            )
            layout.addWidget(scope_btn)
        elif task.get("missionary_id"):
            open_btn = create_button("Open Missionary", "subtle", fixed_height=28)
            open_btn.clicked.connect(
                lambda _=None, missionary_id=task["missionary_id"]:
                self._open_missionary(missionary_id)
            )
            layout.addWidget(open_btn)

        card.mousePressEvent = (
            lambda event, task_id=task["id"]:
            self._task_row_clicked(event, task_id)
        )
        return card

    def _project_row(self, project):
        card = create_card(object_name="OfficeWorkRow")
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        card.setLayout(layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(4)
        title = QLabel(project["title"])
        title.setObjectName("StrongText")
        text_stack.addWidget(title)

        meta = QLabel(
            "  |  ".join([
                project["priority"].title(),
                PROJECT_STATUS_LABELS.get(project["status"], project["status"].title()),
                _format_date(project.get("due_date")),
                project["progress"],
                f"{project['open_tasks']} open",
            ])
        )
        meta.setObjectName("OfficeWorkMeta")
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
        else:
            key = "tasks"
            self.stack.setCurrentIndex(self.tasks_index)

        self._selected_tab = key
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
