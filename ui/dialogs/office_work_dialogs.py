from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.secretary_work_service import SecretaryWorkError
from ui.foundation import (
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    PageHeader,
    create_button,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    create_plain_text_edit,
    setup_dialog_shell,
    show_message,
)


TASK_STATUSES = ["OPEN", "WAITING", "DONE", "ARCHIVED"]
PROJECT_STATUSES = ["ACTIVE", "WAITING", "DONE", "ARCHIVED"]
PRIORITIES = ["LOW", "NORMAL", "IMPORTANT", "CRITICAL"]
APPOINTMENT_FIELDS = [
    ("None", None),
    ("Interpol", "interpol_appointment_date"),
    ("Biometric", "biometric_appointment_date"),
    ("Pickup", "pickup_appointment_date"),
]


def _qdate_from_date(value):
    if value is None:
        return QDate.currentDate()
    return QDate(value.year, value.month, value.day)


def _date_from_picker(widget):
    qdate = widget.getDate() if hasattr(widget, "getDate") else widget.date()
    return qdate.toPython()


class _OfficeWorkDialogBase(MaskDialogBase):
    def __init__(self, title, subtitle, service, parent=None):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = FLUENT_AVAILABLE and fluent_parent is not None
        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.service = service
        self.saved_item = None
        self.setWindowTitle(title)
        self.surface = setup_dialog_shell(self, surface_width=560)
        self._dialog_title = title
        self._dialog_subtitle = subtitle

    def _onDone(self, code):
        if self._use_fluent_dialog:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def _build_shell(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface.setLayout(layout)

        layout.addWidget(PageHeader(self._dialog_title, self._dialog_subtitle))

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(24, 20, 24, 20)
        self.body_layout.setSpacing(12)
        body.setLayout(self.body_layout)
        layout.addWidget(body)

        footer = DialogFooter()
        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)
        footer.add_action(cancel_btn)

        self.save_btn = create_button("Save", "primary")
        self.save_btn.clicked.connect(self._save)
        footer.add_action(self.save_btn)
        layout.addWidget(footer)

    def _field(self, label_text, control):
        wrapper = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        wrapper.setLayout(layout)

        label = QLabel(label_text)
        label.setObjectName("OfficeWorkFieldLabel")
        layout.addWidget(label)
        layout.addWidget(control)
        return wrapper

    def _validate_title(self):
        if self.title_input.text().strip():
            return True

        show_message(
            self,
            "Title Required",
            "Enter a title before saving.",
            kind="warning",
        )
        return False

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)


class TaskDialog(_OfficeWorkDialogBase):
    def __init__(self, service, task=None, parent=None):
        self.task = task or {}
        super().__init__(
            "Edit Task" if task else "Add Task",
            "Capture secretary work with a due date, priority, and optional links.",
            service,
            parent,
        )
        self._build_shell()
        self._build_form()

    def _build_form(self):
        self.title_input = create_line_edit("Task title")
        self.title_input.setText(self.task.get("title", ""))
        self.body_layout.addWidget(self._field("Title", self.title_input))

        self.description_input = create_plain_text_edit()
        self.description_input.setPlaceholderText("Notes or details")
        self.description_input.setPlainText(self.task.get("description", ""))
        self.description_input.setFixedHeight(86)
        self.body_layout.addWidget(
            self._field("Description", self.description_input)
        )

        self.status_combo = create_combo_box()
        for status in TASK_STATUSES:
            self.status_combo.addItem(status.title(), status)
        self._set_combo_data(self.status_combo, self.task.get("status", "OPEN"))
        self.body_layout.addWidget(self._field("Status", self.status_combo))

        self.priority_combo = create_combo_box()
        for priority in PRIORITIES:
            self.priority_combo.addItem(priority.title(), priority)
        self._set_combo_data(
            self.priority_combo,
            self.task.get("priority", "NORMAL"),
        )
        self.body_layout.addWidget(self._field("Priority", self.priority_combo))

        self.due_date_input = create_date_picker()
        self.due_date_input.setDate(_qdate_from_date(self.task.get("due_date")))
        self.no_due_date_check = QCheckBox("No due date")
        self.no_due_date_check.setChecked(self.task.get("due_date") is None)
        self.no_due_date_check.toggled.connect(self.due_date_input.setDisabled)
        self.due_date_input.setDisabled(self.no_due_date_check.isChecked())
        self.body_layout.addWidget(self._field("Due Date", self.due_date_input))
        self.body_layout.addWidget(self.no_due_date_check)

        self.project_combo = create_combo_box()
        self.project_combo.addItem("No project", None)
        for project in self.service.project_options():
            self.project_combo.addItem(project["title"], project["id"])
        self._set_combo_data(self.project_combo, self.task.get("project_id"))
        self.body_layout.addWidget(self._field("Project", self.project_combo))

        self.missionary_combo = create_combo_box()
        self.missionary_combo.addItem("No missionary", None)
        for missionary in self.service.missionary_options():
            self.missionary_combo.addItem(missionary["name"], missionary["id"])
        self._set_combo_data(
            self.missionary_combo,
            self.task.get("missionary_id"),
        )
        self.body_layout.addWidget(self._field("Missionary", self.missionary_combo))

        self.appointment_combo = create_combo_box()
        for label, field in APPOINTMENT_FIELDS:
            self.appointment_combo.addItem(label, field)
        self._set_combo_data(
            self.appointment_combo,
            self.task.get("appointment_field"),
        )
        self.body_layout.addWidget(
            self._field("Appointment Link", self.appointment_combo)
        )

    def _payload(self):
        return {
            "title": self.title_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "status": self.status_combo.currentData(),
            "priority": self.priority_combo.currentData(),
            "due_date": (
                None
                if self.no_due_date_check.isChecked()
                else _date_from_picker(self.due_date_input)
            ),
            "project_id": self.project_combo.currentData(),
            "missionary_id": self.missionary_combo.currentData(),
            "appointment_field": self.appointment_combo.currentData(),
        }

    def _save(self):
        if not self._validate_title():
            return

        try:
            payload = self._payload()
            if self.task.get("id"):
                self.saved_item = self.service.update_task(
                    self.task["id"],
                    **payload,
                )
            else:
                self.saved_item = self.service.create_task(**payload)
            self.accept()
        except SecretaryWorkError as exc:
            show_message(self, "Office Work", str(exc), kind="warning")


class ProjectDialog(_OfficeWorkDialogBase):
    def __init__(self, service, project=None, parent=None):
        self.project = project or {}
        super().__init__(
            "Edit Project" if project else "Add Project",
            "Group related secretary work and track progress.",
            service,
            parent,
        )
        self._build_shell()
        self._build_form()

    def _build_form(self):
        self.title_input = create_line_edit("Project title")
        self.title_input.setText(self.project.get("title", ""))
        self.body_layout.addWidget(self._field("Title", self.title_input))

        self.description_input = create_plain_text_edit()
        self.description_input.setPlaceholderText("Project notes")
        self.description_input.setPlainText(self.project.get("description", ""))
        self.description_input.setFixedHeight(100)
        self.body_layout.addWidget(
            self._field("Description", self.description_input)
        )

        self.status_combo = create_combo_box()
        for status in PROJECT_STATUSES:
            self.status_combo.addItem(status.title(), status)
        self._set_combo_data(
            self.status_combo,
            self.project.get("status", "ACTIVE"),
        )
        self.body_layout.addWidget(self._field("Status", self.status_combo))

        self.priority_combo = create_combo_box()
        for priority in PRIORITIES:
            self.priority_combo.addItem(priority.title(), priority)
        self._set_combo_data(
            self.priority_combo,
            self.project.get("priority", "NORMAL"),
        )
        self.body_layout.addWidget(self._field("Priority", self.priority_combo))

        self.due_date_input = create_date_picker()
        self.due_date_input.setDate(_qdate_from_date(self.project.get("due_date")))
        self.no_due_date_check = QCheckBox("No due date")
        self.no_due_date_check.setChecked(self.project.get("due_date") is None)
        self.no_due_date_check.toggled.connect(self.due_date_input.setDisabled)
        self.due_date_input.setDisabled(self.no_due_date_check.isChecked())
        self.body_layout.addWidget(self._field("Due Date", self.due_date_input))
        self.body_layout.addWidget(self.no_due_date_check)

    def _payload(self):
        return {
            "title": self.title_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "status": self.status_combo.currentData(),
            "priority": self.priority_combo.currentData(),
            "due_date": (
                None
                if self.no_due_date_check.isChecked()
                else _date_from_picker(self.due_date_input)
            ),
        }

    def _save(self):
        if not self._validate_title():
            return

        try:
            payload = self._payload()
            if self.project.get("id"):
                self.saved_item = self.service.update_project(
                    self.project["id"],
                    **payload,
                )
            else:
                self.saved_item = self.service.create_project(**payload)
            self.accept()
        except SecretaryWorkError as exc:
            show_message(self, "Office Work", str(exc), kind="warning")
