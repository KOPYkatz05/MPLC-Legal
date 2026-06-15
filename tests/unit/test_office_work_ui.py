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
        self.completed_projects = []
        self.archived_projects = []

    def summary(self):
        return {
            "open": 1,
            "overdue": 1,
            "due_today": 0,
            "waiting": 0,
        }

    def grouped_tasks(self, **filters):
        _ = filters
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
                    "waiting_reason": None,
                    "waiting_reason_label": "",
                }
            ],
            "today": [],
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
                "open_tasks": 1,
                "done_tasks": 1,
                "total_tasks": 2,
                "progress": "1/2 done",
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


def test_office_work_project_archive_action(qapp):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)

    try:
        page._archive_project(7)

        assert service.archived_projects == [7]
    finally:
        page.close()


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
