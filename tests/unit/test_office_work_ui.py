from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import Qt

from ui.dialogs import office_work_dialogs
from ui.dialogs.office_work_dialogs import ProjectDialog, TaskDialog
from ui.main_window import MainWindow
from ui.pages.office_work_page import OfficeWorkPage


class FakeSecretaryWorkService:
    def __init__(self):
        self.completed_tasks = []
        self.archived_tasks = []
        self.deleted_tasks = []
        self.ready_tasks = []
        self.reopened_tasks = []
        self.completed_projects = []
        self.archived_projects = []
        self.last_task_filters = {}

    def summary(self):
        return {
            "open": 1,
            "ready": 1,
            "follow_up": 1,
            "overdue": 1,
            "due_today": 0,
            "waiting": 0,
        }

    def grouped_tasks(self, **filters):
        self.last_task_filters = filters
        return {
            "overdue": [
                {
                    "id": 1,
                    "title": "Call mission office",
                    "description": "",
                    "status": "OPEN",
                    "priority": "IMPORTANT",
                    "due_date": None,
                    "due_group": "overdue",
                    "project_id": None,
                    "project_title": "",
                    "missionary_id": None,
                    "missionary_name": "",
                    "missionary_ids": [],
                    "missionary_names": [],
                    "missionary_count": 0,
                    "scope_label": "",
                    "group_id": None,
                    "group_scope_label": "",
                    "is_group_task": False,
                    "appointment_field": None,
                    "appointment_label": "",
                    "task_type": "DOCUMENT",
                    "task_type_label": "Document",
                    "related_stage": "INTERPOL",
                    "related_document_type": "PASSPORT",
                    "related_document_label": "Passport",
                    "automation_source": "process_automation",
                    "automation_key": "test:auto",
                    "automation_status_reason": "",
                    "waiting_reason": None,
                    "waiting_reason_label": "",
                    "waiting_follow_up_date": None,
                    "waiting_follow_up_label": "",
                }
            ],
            "today": [],
            "ready_to_review": [],
            "this_week": [],
            "later": [],
            "no_due_date": [],
        }

    def list_projects(self, **filters):
        _ = filters
        return [
            {
                "id": 7,
                "title": "June arrivals",
                "description": "",
                "status": "ACTIVE",
                "priority": "NORMAL",
                "due_date": None,
                "open_tasks": 3,
                "todo_tasks": 1,
                "ready_tasks": 1,
                "waiting_tasks": 1,
                "done_tasks": 1,
                "total_tasks": 4,
                "progress": "1/4 done",
            }
        ]

    def project_options(self):
        return [{"id": 7, "title": "June arrivals"}]

    def missionary_options(self):
        return [
            {"id": 4, "name": "Test Missionary"},
            {"id": 8, "name": "Second Missionary"},
        ]

    def group_options(self):
        return [
            {
                "id": 12,
                "name": "Llegadas June 3rd",
                "missionary_ids": [4, 8],
                "member_count": 2,
            }
        ]

    def complete_task(self, task_id):
        self.completed_tasks.append(task_id)

    def mark_task_ready(self, task_id):
        self.ready_tasks.append(task_id)

    def reopen_task(self, task_id):
        self.reopened_tasks.append(task_id)

    def archive_task(self, task_id):
        self.archived_tasks.append(task_id)

    def delete_task(self, task_id):
        self.deleted_tasks.append(task_id)
        return True

    def complete_project(self, project_id):
        self.completed_projects.append(project_id)

    def archive_project(self, project_id):
        self.archived_projects.append(project_id)


def test_office_work_page_loads_with_mocked_service(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        assert page._selected_tab == "tasks"
        assert page.stack.currentIndex() == page.tasks_index
    finally:
        page.close()


def test_office_work_page_can_filter_to_project(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        page._show_project_tasks(7)

        assert page._project_filter_id == 7
        assert page._selected_tab == "tasks"
    finally:
        page.close()


def test_task_dialog_validates_required_title(monkeypatch, qapp):
    _ = qapp
    messages = []
    monkeypatch.setattr(
        office_work_dialogs,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("")

        assert dialog._validate_title() is False
        assert messages
    finally:
        dialog.close()


def test_task_dialog_accepts_due_date_defaults(qapp):
    _ = qapp
    target = date(2026, 6, 12)
    dialog = TaskDialog(
        FakeSecretaryWorkService(),
        defaults={"due_date": target},
    )

    try:
        dialog.title_input.setText("Prepare packet")

        assert dialog.no_due_date_check.isChecked() is False
        assert dialog._payload()["due_date"] == target
        assert dialog.windowTitle() == "Add Task"
    finally:
        dialog.close()


def test_task_dialog_payload_includes_classification_fields(qapp):
    _ = qapp
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("Classified task")
        dialog._set_combo_data(dialog.task_type_combo, "DOCUMENT")
        dialog._set_combo_data(dialog.related_stage_combo, "INTERPOL")
        dialog._set_combo_data(dialog.related_document_combo, "PASSPORT")

        payload = dialog._payload()

        assert payload["task_type"] == "DOCUMENT"
        assert payload["related_stage"] == "INTERPOL"
        assert payload["related_document_type"] == "PASSPORT"
    finally:
        dialog.close()


def test_task_dialog_payload_includes_waiting_follow_up_date(qapp):
    _ = qapp
    target = date(2026, 6, 18)
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("Waiting task")
        dialog._set_combo_data(dialog.status_combo, "WAITING")
        dialog._set_combo_data(dialog.waiting_reason_combo, "DOCUMENT")
        dialog.waiting_follow_up_input.setDate(
            office_work_dialogs._qdate_from_date(target)
        )
        dialog.no_waiting_follow_up_check.setChecked(False)

        payload = dialog._payload()

        assert payload["waiting_reason"] == "DOCUMENT"
        assert payload["waiting_follow_up_date"] == target
    finally:
        dialog.close()


def test_task_dialog_payload_supports_multiple_missionaries(qapp):
    _ = qapp
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("Shared prep")
        first = dialog.missionary_picker.list_widget.item(0)
        second = dialog.missionary_picker.list_widget.item(1)
        first.setCheckState(Qt.Checked)
        second.setCheckState(Qt.Checked)

        payload = dialog._payload()

        assert payload["missionary_ids"] == [4, 8]
        assert payload["missionary_id"] is None
    finally:
        dialog.close()


def test_task_dialog_group_selection_sets_current_members(qapp):
    _ = qapp
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog._set_combo_data(dialog.group_combo, 12)

        assert dialog.missionary_picker.selected_ids() == [4, 8]
        assert dialog._payload()["group_id"] == 12
    finally:
        dialog.close()


def test_task_dialog_starts_with_details_collapsed(qapp):
    _ = qapp
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        assert dialog.details_widget.isVisible() is False
        assert dialog.details_button.text() == "More details"
    finally:
        dialog.close()


def test_task_dialog_requires_waiting_reason(monkeypatch, qapp):
    _ = qapp
    messages = []
    monkeypatch.setattr(
        office_work_dialogs,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("Waiting task")
        dialog._set_combo_data(dialog.status_combo, "WAITING")
        dialog._save()

        assert messages
        assert dialog.details_widget.isHidden() is False
    finally:
        dialog.close()


def test_office_work_task_archive_and_delete_actions(monkeypatch, qapp):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)
    monkeypatch.setattr(
        "ui.pages.office_work_page.show_message",
        lambda *args, **kwargs: 16384,
    )

    try:
        page._archive_task(1)
        page._delete_task(1)

        assert service.archived_tasks == [1]
        assert service.deleted_tasks == [1]
    finally:
        page.close()


def test_office_work_ready_transition_actions(qapp):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)

    try:
        page._mark_task_ready(1)
        page._reopen_task(2)

        assert service.ready_tasks == [1]
        assert service.reopened_tasks == [2]
    finally:
        page.close()


def test_office_work_task_presets_drive_existing_filters(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        page._apply_task_preset("ready")
        assert page.task_status_filter.currentData() == "READY"

        page._apply_task_preset("follow_up")
        assert page.task_follow_up_filter.currentData() == "due"
        assert page.service.last_task_filters["waiting_follow_up"] == "due"

        page._set_combo_data(page.task_waiting_reason_filter, "MISSIONARY")
        page.render_tasks()
        assert page.service.last_task_filters["waiting_reason"] == "MISSIONARY"

        page._set_combo_data(page.task_stage_filter, "INTERPOL")
        page.render_tasks()
        assert page.service.last_task_filters["related_stage"] == "INTERPOL"

        page._apply_task_preset("appointments")
        assert page.task_type_filter.currentData() == "APPOINTMENT"

        page._apply_task_preset("critical")
        assert page.task_priority_filter.currentData() == "CRITICAL"
    finally:
        page.close()


def test_office_work_task_opens_alert_workspace(qapp):
    _ = qapp
    opened = []
    page = OfficeWorkPage(
        main_window=SimpleNamespace(
            open_alert_workspace=lambda task_id, return_key="office_work":
            opened.append((task_id, return_key))
        ),
        service=FakeSecretaryWorkService(),
    )

    try:
        page._open_task_workspace(1)

        assert opened == [(1, "office_work")]
    finally:
        page.close()


def test_office_work_project_archive_action(qapp):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)

    try:
        page._archive_project(7)

        assert service.archived_projects == [7]
    finally:
        page.close()


def test_office_work_project_task_breakdown_labels_counts():
    assert OfficeWorkPage._project_task_breakdown({
        "todo_tasks": 1,
        "ready_tasks": 2,
        "waiting_tasks": 3,
        "open_tasks": 6,
    }) == "1 to do, 2 ready, 3 waiting"

    assert OfficeWorkPage._project_task_breakdown({
        "open_tasks": 0,
    }) == "0 open"


def test_project_dialog_validates_required_title(monkeypatch, qapp):
    _ = qapp
    messages = []
    monkeypatch.setattr(
        office_work_dialogs,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = ProjectDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("")

        assert dialog._validate_title() is False
        assert messages
    finally:
        dialog.close()


def test_main_window_refreshes_office_work_page():
    window = MainWindow.__new__(MainWindow)
    calls = []
    window.dashboard_page = SimpleNamespace(load_data=lambda: None)
    window.missionaries_page = SimpleNamespace(load_data=lambda: None)
    window.office_work_page = SimpleNamespace(load_data=lambda: calls.append("office"))
    window.calendar_page = SimpleNamespace(load_data=lambda: None)
    window.reports_page = SimpleNamespace(load_data=lambda: None)
    window.trash_page = SimpleNamespace(load_data=lambda: None)

    MainWindow._on_nav_changed(window, "office_work", 3)

    assert calls == ["office"]
