from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.secretary_work_service import (
    TASK_TYPE_LABELS,
    WAITING_REASON_LABELS,
    SecretaryWorkError,
)
from database.models.secretary_work import PRIORITIES, TASK_STATUSES, TASK_TYPES
from ui.foundation import (
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    create_button,
    create_check_box,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    create_list_widget,
    create_plain_text_edit,
    create_search_edit,
    setup_dialog_shell,
    show_message,
)
from utils.constants import DOCUMENTS, WORKFLOW_STAGES


PROJECT_STATUSES = ["ACTIVE", "WAITING", "DONE", "ARCHIVED"]
APPOINTMENT_FIELDS = [
    ("None", None),
    ("Interpol", "interpol_appointment_date"),
    ("Biometric", "biometric_appointment_date"),
    ("Pickup", "pickup_appointment_date"),
]
TASK_STATUS_LABELS = {
    "OPEN": "To Do",
    "READY": "Ready",
    "WAITING": "Waiting",
    "DONE": "Done",
    "ARCHIVED": "Archived",
}


class MissionaryScopePicker(QWidget):
    def __init__(self, missionaries, parent=None):
        super().__init__(parent)
        self._items_by_id = {}

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        self.search_input = create_search_edit("Search missionaries")
        self.search_input.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_input)

        self.summary_label = QLabel("No missionaries selected")
        self.summary_label.setObjectName("MutedText")
        layout.addWidget(self.summary_label)

        self.list_widget = create_list_widget("TaskMissionaryPicker")
        self.list_widget.setFixedHeight(150)
        self.list_widget.itemChanged.connect(lambda _=None: self._update_summary())
        layout.addWidget(self.list_widget)

        for missionary in missionaries:
            item = QListWidgetItem(missionary["name"])
            item.setData(Qt.UserRole, missionary["id"])
            item.setFlags(
                item.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsSelectable
                | Qt.ItemIsEnabled
            )
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)
            self._items_by_id[missionary["id"]] = item

    def selected_ids(self):
        ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def set_selected_ids(self, missionary_ids):
        selected = set(missionary_ids or [])
        self.list_widget.blockSignals(True)
        try:
            for index in range(self.list_widget.count()):
                item = self.list_widget.item(index)
                item.setCheckState(
                    Qt.Checked
                    if item.data(Qt.UserRole) in selected
                    else Qt.Unchecked
                )
        finally:
            self.list_widget.blockSignals(False)
        self._update_summary()

    def selected_names(self):
        names = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                names.append(item.text())
        return names

    def _filter_items(self, text):
        needle = text.strip().casefold()
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(needle not in item.text().casefold())

    def _update_summary(self):
        names = self.selected_names()
        if not names:
            self.summary_label.setText("No missionaries selected")
        elif len(names) == 1:
            self.summary_label.setText(names[0])
        else:
            self.summary_label.setText(f"{len(names)} missionaries selected")


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

        header = QFrame()
        header.setObjectName("OfficeWorkDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = QLabel(self._dialog_title)
        title.setObjectName("OfficeWorkDialogTitle")
        subtitle = QLabel(self._dialog_subtitle)
        subtitle.setObjectName("OfficeWorkDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("OfficeWorkDialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(18, 16, 18, 16)
        self.body_layout.setSpacing(12)
        body.setLayout(self.body_layout)
        layout.addWidget(body)

        footer = DialogFooter()
        footer.setObjectName("OfficeWorkDialogFooter")
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
    def __init__(self, service, task=None, defaults=None, parent=None):
        is_edit = task is not None
        self.task = task or dict(defaults or {})
        super().__init__(
            "Edit Task" if is_edit else "Add Task",
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

        self.status_combo = create_combo_box()
        for status in TASK_STATUSES:
            self.status_combo.addItem(
                TASK_STATUS_LABELS.get(status, status.title()),
                status,
            )
        self._set_combo_data(self.status_combo, self.task.get("status", "OPEN"))

        self.priority_combo = create_combo_box()
        for priority in PRIORITIES:
            self.priority_combo.addItem(priority.title(), priority)
        self._set_combo_data(
            self.priority_combo,
            self.task.get("priority", "NORMAL"),
        )
        self.body_layout.addWidget(self._field("Priority", self.priority_combo))

        self.work_date_input = create_date_picker()
        self.work_date_input.setDate(_qdate_from_date(self.task.get("work_date")))
        self.no_work_date_check = create_check_box("No work date")
        self.no_work_date_check.setChecked(self.task.get("work_date") is None)
        self.no_work_date_check.toggled.connect(self.work_date_input.setDisabled)
        self.work_date_input.setDisabled(self.no_work_date_check.isChecked())
        self.body_layout.addWidget(self._field("Do On", self.work_date_input))
        self.body_layout.addWidget(self.no_work_date_check)

        self.due_date_input = create_date_picker()
        self.due_date_input.setDate(_qdate_from_date(self.task.get("due_date")))
        self.no_due_date_check = create_check_box("No due date")
        self.no_due_date_check.setChecked(self.task.get("due_date") is None)
        self.no_due_date_check.toggled.connect(self.due_date_input.setDisabled)
        self.due_date_input.setDisabled(self.no_due_date_check.isChecked())
        self.body_layout.addWidget(
            self._field("Must Be Done By", self.due_date_input)
        )
        self.body_layout.addWidget(self.no_due_date_check)

        self.project_combo = create_combo_box()
        self.project_combo.addItem("No project", None)
        for project in self.service.project_options():
            self.project_combo.addItem(project["title"], project["id"])
        self._set_combo_data(self.project_combo, self.task.get("project_id"))

        self._group_options = (
            self.service.group_options()
            if hasattr(self.service, "group_options")
            else []
        )
        self._group_members_by_id = {
            group["id"]: group.get("missionary_ids", [])
            for group in self._group_options
        }

        self.group_combo = create_combo_box()
        self.group_combo.addItem("No group", None)
        for group in self._group_options:
            count = group.get("member_count", len(group.get("missionary_ids", [])))
            self.group_combo.addItem(
                f"{group['name']} ({count})",
                group["id"],
            )
        self._set_combo_data(self.group_combo, self.task.get("group_id"))
        self.group_combo.currentIndexChanged.connect(
            lambda _=None: self._group_changed()
        )

        selected_missionary_ids = self.task.get("missionary_ids")
        if selected_missionary_ids is None and self.task.get("missionary_id"):
            selected_missionary_ids = [self.task.get("missionary_id")]
        self.missionary_picker = MissionaryScopePicker(
            self.service.missionary_options(),
        )
        self.missionary_picker.set_selected_ids(selected_missionary_ids or [])
        if self.task.get("group_id") and not selected_missionary_ids:
            self.missionary_picker.set_selected_ids(
                self._group_members_by_id.get(self.task.get("group_id"), [])
            )
        self.body_layout.addWidget(self._field("Applies To", self.missionary_picker))

        self.appointment_combo = create_combo_box()
        for label, field in APPOINTMENT_FIELDS:
            self.appointment_combo.addItem(label, field)
        self._set_combo_data(
            self.appointment_combo,
            self.task.get("appointment_field"),
        )

        self.task_type_combo = create_combo_box()
        for task_type in TASK_TYPES:
            self.task_type_combo.addItem(
                TASK_TYPE_LABELS.get(task_type, task_type.title()),
                task_type,
            )
        self._set_combo_data(
            self.task_type_combo,
            self.task.get("task_type", "CUSTOM"),
        )

        self.related_stage_combo = create_combo_box()
        self.related_stage_combo.addItem("No related stage", None)
        for stage in WORKFLOW_STAGES:
            self.related_stage_combo.addItem(stage.title(), stage)
        self._set_combo_data(
            self.related_stage_combo,
            self.task.get("related_stage"),
        )

        self.related_document_combo = create_combo_box()
        self.related_document_combo.addItem("No related document", None)
        for document_type, definition in sorted(
            DOCUMENTS.items(),
            key=lambda item: item[1].get("label", item[0]),
        ):
            self.related_document_combo.addItem(
                definition.get("label", document_type),
                document_type,
            )
        self._set_combo_data(
            self.related_document_combo,
            self.task.get("related_document_type"),
        )

        self.details_button = create_button(
            "More details",
            "subtle",
            fixed_height=30,
        )
        self.details_button.clicked.connect(self._toggle_details)
        self.body_layout.addWidget(self.details_button)

        self.details_widget = QWidget()
        self.details_widget.setObjectName("TaskDialogDetails")
        self.details_widget.setAttribute(Qt.WA_StyledBackground, True)
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(12)
        self.details_widget.setLayout(details_layout)

        details_layout.addWidget(self._field("Description", self.description_input))
        details_layout.addWidget(self._field("Project", self.project_combo))
        details_layout.addWidget(self._field("Group", self.group_combo))
        details_layout.addWidget(
            self._field("Appointment Link", self.appointment_combo)
        )
        details_layout.addWidget(self._field("Task Type", self.task_type_combo))
        details_layout.addWidget(
            self._field("Related Stage", self.related_stage_combo)
        )
        details_layout.addWidget(
            self._field("Related Document", self.related_document_combo)
        )
        details_layout.addWidget(self._field("Status", self.status_combo))

        self.waiting_reason_combo = create_combo_box()
        self.waiting_reason_combo.addItem("Select reason", None)
        for reason, label in WAITING_REASON_LABELS.items():
            self.waiting_reason_combo.addItem(label, reason)
        self._set_combo_data(
            self.waiting_reason_combo,
            self.task.get("waiting_reason"),
        )
        self.waiting_reason_field = self._field(
            "Waiting Reason",
            self.waiting_reason_combo,
        )
        details_layout.addWidget(self.waiting_reason_field)

        self.waiting_follow_up_input = create_date_picker()
        self.waiting_follow_up_input.setDate(
            _qdate_from_date(self.task.get("waiting_follow_up_date"))
        )
        self.no_waiting_follow_up_check = create_check_box("No follow-up date")
        self.no_waiting_follow_up_check.setChecked(
            self.task.get("waiting_follow_up_date") is None
        )
        self.no_waiting_follow_up_check.toggled.connect(
            self.waiting_follow_up_input.setDisabled
        )
        self.waiting_follow_up_input.setDisabled(
            self.no_waiting_follow_up_check.isChecked()
        )
        self.waiting_follow_up_field = self._field(
            "Follow Up On",
            self.waiting_follow_up_input,
        )
        details_layout.addWidget(self.waiting_follow_up_field)
        details_layout.addWidget(self.no_waiting_follow_up_check)

        history_widget = self._status_history_widget()
        if history_widget is not None:
            details_layout.addWidget(history_widget)

        self.body_layout.addWidget(self.details_widget)
        self._set_details_visible(self.status_combo.currentData() == "WAITING")
        self.status_combo.currentIndexChanged.connect(
            lambda _=None: self._status_changed()
        )
        self._sync_waiting_reason_visibility()

    def _payload(self):
        missionary_ids = self.missionary_picker.selected_ids()
        return {
            "title": self.title_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "status": self.status_combo.currentData(),
            "priority": self.priority_combo.currentData(),
            "work_date": (
                None
                if self.no_work_date_check.isChecked()
                else _date_from_picker(self.work_date_input)
            ),
            "due_date": (
                None
                if self.no_due_date_check.isChecked()
                else _date_from_picker(self.due_date_input)
            ),
            "project_id": self.project_combo.currentData(),
            "missionary_id": missionary_ids[0] if len(missionary_ids) == 1 else None,
            "missionary_ids": missionary_ids,
            "group_id": self.group_combo.currentData(),
            "appointment_field": self.appointment_combo.currentData(),
            "task_type": self.task_type_combo.currentData(),
            "related_stage": self.related_stage_combo.currentData(),
            "related_document_type": self.related_document_combo.currentData(),
            "waiting_reason": self.waiting_reason_combo.currentData(),
            "waiting_follow_up_date": (
                None
                if self.no_waiting_follow_up_check.isChecked()
                else _date_from_picker(self.waiting_follow_up_input)
            ),
        }

    def _save(self):
        if not self._validate_title():
            return
        if (
            self.status_combo.currentData() == "WAITING"
            and not self.waiting_reason_combo.currentData()
        ):
            self.details_widget.setVisible(True)
            self.details_button.setText("Hide details")
            show_message(
                self,
                "Waiting Reason Required",
                "Choose why this task is waiting before saving.",
                kind="warning",
            )
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

    def _toggle_details(self):
        visible = self.details_widget.isHidden()
        self._set_details_visible(visible)

    def _set_details_visible(self, visible):
        self.details_widget.setVisible(visible)
        self.details_button.setText("Hide details" if visible else "More details")

    def _sync_waiting_reason_visibility(self):
        is_waiting = self.status_combo.currentData() == "WAITING"
        self.waiting_reason_field.setVisible(is_waiting)
        self.waiting_follow_up_field.setVisible(is_waiting)
        self.no_waiting_follow_up_check.setVisible(is_waiting)

    def _status_changed(self):
        self._sync_waiting_reason_visibility()
        if self.status_combo.currentData() == "WAITING":
            self._set_details_visible(True)

    def _group_changed(self):
        group_id = self.group_combo.currentData()
        if not group_id:
            return
        self.missionary_picker.set_selected_ids(
            self._group_members_by_id.get(group_id, [])
        )

    def _status_history_widget(self):
        task_id = self.task.get("id")
        if not task_id or not hasattr(self.service, "get_task_status_history"):
            return None

        history = self.service.get_task_status_history(task_id)
        if not history:
            return None

        frame = QFrame()
        frame.setObjectName("TaskDialogStatusHistory")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        frame.setLayout(layout)

        title = QLabel("Recent Status Changes")
        title.setObjectName("OfficeWorkFieldLabel")
        layout.addWidget(title)

        for item in history:
            when = item.get("created_at")
            when_text = when.strftime("%b %d, %Y") if when else ""
            summary = item.get("summary") or ""
            note = item.get("note") or ""
            parts = [part for part in (summary, when_text, note) if part]
            row = QLabel(" - ".join(parts))
            row.setObjectName("MutedText")
            row.setWordWrap(True)
            layout.addWidget(row)

        return frame


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
        self.no_due_date_check = create_check_box("No due date")
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
