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
    PageHeader,
    StatCard,
    create_button,
    create_card,
    create_combo_box,
    create_pivot,
    create_scroll_area,
    create_search_edit,
    divider,
    fluent_icon,
)
from utils.logger import logger


TASK_GROUP_LABELS = dict(TASK_GROUPS)
PRIORITY_COLORS = {
    "LOW": "#71717A",
    "NORMAL": "#2563EB",
    "IMPORTANT": "#D97706",
    "CRITICAL": "#DC2626",
}


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

        self.header = PageHeader(
            "Office Work",
            "Track secretary tasks, projects, and follow-up work.",
            [self._build_header_action()],
        )
        outer.addWidget(self.header)
        outer.addWidget(divider())

        self._build_tabs()
        outer.addWidget(self.tab_bar)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)

        self._build_tasks_tab()
        self._build_projects_tab()
        self._select_tab("tasks")

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
        self.tab_bar.setObjectName("OfficeWorkTabs")
        layout = QHBoxLayout()
        layout.setContentsMargins(32, 8, 32, 8)
        layout.setSpacing(8)
        self.tab_bar.setLayout(layout)

        self.tab_control = create_pivot()
        self.tab_buttons = {}
        if self.tab_control is not None:
            self.tab_control.addItem("tasks", "Tasks")
            self.tab_control.addItem("projects", "Projects")
            self.tab_control.currentItemChanged.connect(self._select_tab)
            layout.addWidget(self.tab_control)
            layout.addStretch()
            return

        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        for key, title in [("tasks", "Tasks"), ("projects", "Projects")]:
            button = QPushButton(title)
            button.setObjectName("OfficeWorkTabButton")
            button.setCheckable(True)
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
        self.task_content_layout.setContentsMargins(32, 24, 32, 24)
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
        self.project_content_layout.setContentsMargins(32, 24, 32, 24)
        self.project_content_layout.setSpacing(16)
        content.setLayout(self.project_content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)
        self.projects_index = self.stack.addWidget(tab)

    def _build_task_filters(self):
        self.task_filter_bar = FilterBar()

        self.task_search = create_search_edit("Search tasks")
        self.task_search.textChanged.connect(self.render_tasks)
        self.task_filter_bar.add_filter(self.task_search, stretch=1)

        self.task_status_filter = create_combo_box()
        self.task_status_filter.addItem("Visible", None)
        self.task_status_filter.addItem("All", "ALL")
        for status in TASK_STATUSES:
            self.task_status_filter.addItem(status.title(), status)
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

        self.project_search = create_search_edit("Search projects")
        self.project_search.textChanged.connect(self.render_projects)
        self.project_filter_bar.add_filter(self.project_search, stretch=1)

        self.project_status_filter = create_combo_box()
        self.project_status_filter.addItem("Visible", None)
        self.project_status_filter.addItem("All", "ALL")
        for status in PROJECT_STATUSES:
            self.project_status_filter.addItem(status.title(), status)
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
        self._refresh_task_filter_options()
        self.render_tasks()
        self.render_projects()

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
        row.setSpacing(16)
        for key, label, color in [
            ("open", "Open", "#2563EB"),
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
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        card.setLayout(layout)

        accent = QFrame()
        accent.setObjectName("OfficeWorkPriorityAccent")
        accent.setFixedWidth(4)
        accent.setStyleSheet(
            "QFrame#OfficeWorkPriorityAccent {"
            f"background-color: {PRIORITY_COLORS.get(task['priority'], '#71717A')};"
            "border-radius: 2px;"
            "}"
        )
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
            task["status"].title(),
        ]
        if task.get("project_title"):
            meta_parts.append(task["project_title"])
        if task.get("missionary_name"):
            meta_parts.append(task["missionary_name"])
        meta = QLabel("  |  ".join(meta_parts))
        meta.setObjectName("MutedText")
        text_stack.addWidget(meta)
        layout.addLayout(text_stack, stretch=1)

        if task["status"] not in {"DONE", "ARCHIVED"}:
            done_btn = create_button("Done", "success", fixed_height=28)
            done_btn.clicked.connect(lambda _=None, task_id=task["id"]: self._complete_task(task_id))
            layout.addWidget(done_btn)

        edit_btn = create_button("Edit", "secondary", fixed_height=28)
        edit_btn.clicked.connect(lambda _=None, item=task: self._edit_task(item))
        layout.addWidget(edit_btn)

        if task.get("missionary_id"):
            open_btn = create_button("Open Missionary", "subtle", fixed_height=28)
            open_btn.clicked.connect(
                lambda _=None, missionary_id=task["missionary_id"]:
                self._open_missionary(missionary_id)
            )
            layout.addWidget(open_btn)

        return card

    def _project_row(self, project):
        card = create_card(object_name="OfficeWorkRow")
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
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
                project["status"].title(),
                _format_date(project.get("due_date")),
                project["progress"],
                f"{project['open_tasks']} open",
            ])
        )
        meta.setObjectName("MutedText")
        text_stack.addWidget(meta)
        layout.addLayout(text_stack, stretch=1)

        tasks_btn = create_button("View Tasks", "secondary", fixed_height=28)
        tasks_btn.clicked.connect(
            lambda _=None, project_id=project["id"]:
            self._show_project_tasks(project_id)
        )
        layout.addWidget(tasks_btn)

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

        return card

    def _section_header(self, title, count):
        row = QFrame()
        row.setObjectName("OfficeWorkSectionHeader")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        row.setLayout(layout)

        label = QLabel(f"{title.upper()}  {count}")
        label.setObjectName("SectionHeader")
        layout.addWidget(label)
        layout.addStretch()
        return row

    def _empty_state(self, message):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 30, 24, 30)
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

    def _show_project_tasks(self, project_id):
        self._project_filter_id = project_id
        self._set_combo_data(self.task_project_filter, project_id)
        self._select_tab("tasks")
        self.render_tasks()

    def _project_filter_changed(self):
        self._project_filter_id = self.task_project_filter.currentData()
        self.render_tasks()

    def _add_task(self):
        dialog = TaskDialog(self.service, parent=self)
        if dialog.exec():
            self.load_data()

    def _edit_task(self, task):
        dialog = TaskDialog(self.service, task=task, parent=self)
        if dialog.exec():
            self.load_data()

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

    def _complete_project(self, project_id):
        self.service.complete_project(project_id)
        self.load_data()

    def _open_missionary(self, missionary_id):
        if not self.main_window:
            return

        try:
            session = SessionLocal()
            try:
                missionary = session.query(Missionary).filter_by(id=missionary_id).first()
                if missionary:
                    self.main_window.detail_page.load_missionary(missionary)
                    self.main_window.stack.setCurrentIndex(2)
                    self.main_window.sidebar.setCurrentRow(1)
            finally:
                session.close()
        except Exception:
            logger.exception("Failed to open missionary from Office Work")

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
