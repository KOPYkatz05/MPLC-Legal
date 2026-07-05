from datetime import date, datetime
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QToolButton, QVBoxLayout

from ui.dialogs import office_work_dialogs
from ui.dialogs.office_work_dialogs import ProjectDialog, TaskDialog
from ui.main_window import MainWindow
from ui.pages.office_work_page import OfficeWorkPage, TaskBoardColumn, TaskDropIndicator
from ui.foundation import widgets as foundation_widgets


class FakeSecretaryWorkService:
    def __init__(self):
        self.completed_tasks = []
        self.archived_tasks = []
        self.deleted_tasks = []
        self.ready_tasks = []
        self.reopened_tasks = []
        self.completed_projects = []
        self.archived_projects = []
        self.saved_board_orders = None
        self.last_task_filters = {}
        self.status_history = []

    def summary(self):
        return {
            "open": 1,
            "ready": 1,
            "follow_up": 1,
            "upcoming_follow_up": 1,
            "missing_follow_up": 1,
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
                    "waiting_follow_up_status_label": "",
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

    def get_task_status_history(self, task_id):
        _ = task_id
        return self.status_history

    def complete_task(self, task_id):
        self.completed_tasks.append(task_id)

    def mark_task_ready(self, task_id):
        self.ready_tasks.append(task_id)

    def reopen_task(self, task_id):
        self.reopened_tasks.append(task_id)

    def archive_task(self, task_id):
        self.archived_tasks.append(task_id)

    def save_task_board_orders(self, lane_orders):
        self.saved_board_orders = lane_orders

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


def test_office_work_filters_collapse_into_menu(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        buttons = page.task_filter_bar.findChildren(QPushButton)
        assert [button.text() for button in buttons] == ["Filters"]

        page._show_task_filter_menu()
        menu = page.task_filter_menu
        assert menu is not None
        submenu_titles = [
            action.text()
            for action in menu.actions()
            if action.menu() is not None
        ]
        assert "Quick Filters" in submenu_titles
        assert "Status" in submenu_titles
        assert "Project" in submenu_titles
    finally:
        page.close()


def test_office_work_tasks_render_as_three_column_board(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        columns = page.findChildren(QFrame, "OfficeWorkTaskColumn")
        headers = [
            label.text()
            for column in columns
            for label in column.findChildren(QLabel, "OfficeWorkSectionTitle")
        ]

        assert headers == ["Not Started", "In-Progress", "Completed"]
        assert len(columns) == 3
    finally:
        page.close()


def test_office_work_initial_load_defers_projects(monkeypatch, qapp):
    _ = qapp
    called = []
    monkeypatch.setattr(
        OfficeWorkPage,
        "render_projects",
        lambda self: called.append(True),
    )

    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        assert called == []
        assert page._projects_loaded is False
    finally:
        page.close()


def test_office_work_task_board_groups_into_trello_columns(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        grouped = {
            "overdue": [{"id": 1, "title": "Overdue", "status": "OPEN"}],
            "today": [{"id": 2, "title": "Today", "status": "OPEN"}],
            "ready_to_review": [{"id": 3, "title": "Ready", "status": "READY"}],
            "follow_up_due": [{"id": 4, "title": "Follow Up Due", "status": "WAITING"}],
            "needs_follow_up": [{"id": 5, "title": "Needs Follow-Up", "status": "WAITING"}],
            "scheduled_follow_up": [{"id": 6, "title": "Scheduled Follow-Up", "status": "WAITING"}],
            "this_week": [{"id": 7, "title": "This Week", "status": "OPEN"}],
            "later": [
                {"id": 8, "title": "Later", "status": "OPEN"},
                {"id": 9, "title": "Done", "status": "DONE"},
            ],
        }

        board_groups = page._task_board_groups(grouped)

        assert [task["id"] for task in board_groups["not_started"]] == [8, 1, 7, 2]
        assert [task["id"] for task in board_groups["in_progress"]] == [4, 5, 3, 6]
        assert [task["id"] for task in board_groups["completed"]] == [9]
    finally:
        page.close()


def test_office_work_task_board_column_shows_drop_indicator(qapp):
    _ = qapp
    column = TaskBoardColumn("not_started", lambda *args: None)
    layout = QVBoxLayout()
    column.setLayout(layout)

    header = QLabel("Not Started")
    header.setObjectName("OfficeWorkSectionTitle")
    layout.addWidget(header)

    for task_id in (1, 2):
        pill = QFrame()
        pill.setObjectName("OfficeWorkTaskPill")
        pill.setFixedHeight(64)
        layout.addWidget(pill)

    column._show_drop_indicator(1)

    indicator = column._drop_indicator
    assert indicator is not None
    assert isinstance(indicator, TaskDropIndicator)
    assert indicator.objectName() == "OfficeWorkTaskDropIndicator"
    assert layout.indexOf(indicator) == 2
    assert indicator.height() == column._task_card_height()
    assert indicator.minimumHeight() == column._task_card_height()
    assert indicator.maximumHeight() == column._task_card_height()
    assert column._drop_indicator_animation is None
    assert column._slide_animation_group is not None
    assert indicator.graphicsEffect() is None


def test_office_work_task_board_column_uses_drag_snapshot_for_index(qapp):
    _ = qapp
    column = TaskBoardColumn("not_started", lambda *args: None)
    column._drag_snapshot = [
        (object(), 40),
        (object(), 100),
        (object(), 160),
    ]

    assert column._drop_index(10) == 0
    assert column._drop_index(90) == 1
    assert column._drop_index(140) == 2
    assert column._drop_index(220) == 3


def test_pill_drag_hides_source_during_drag(monkeypatch, qapp):
    _ = qapp
    captured = {}

    class FakeDrag:
        def __init__(self, parent):
            captured["parent"] = parent

        def setMimeData(self, mime):
            captured["mime"] = mime

        def setPixmap(self, pixmap):
            captured["pixmap"] = pixmap

        def setHotSpot(self, hotspot):
            captured["hotspot"] = hotspot

        def exec(self, action):
            captured["action"] = action
            captured["parent_visible_during_drag"] = captured["parent"].isVisible()

    monkeypatch.setattr(foundation_widgets, "QDrag", FakeDrag)

    pill = foundation_widgets.create_pill_action_button(
        "Task",
        drag_payload=123,
    )
    pill.show()
    assert pill.isVisible() is True

    assert pill._start_drag(pill, pill.rect().center()) is True

    assert captured["parent_visible_during_drag"] is False
    assert pill.isVisible() is True
    assert captured["parent"] is pill
    assert captured["action"] == Qt.MoveAction


def test_office_work_task_board_drop_persists_order(qapp, monkeypatch):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)

    try:
        page._board_lane_orders = {
            "not_started": [11, 12],
            "in_progress": [21],
            "completed": [],
        }
        page._board_task_lanes = {
            11: "not_started",
            12: "not_started",
            21: "in_progress",
        }
        page._board_tasks_by_id = {
            11: {"id": 11, "title": "Task 11", "status": "OPEN"},
            12: {"id": 12, "title": "Task 12", "status": "OPEN"},
            21: {"id": 21, "title": "Task 21", "status": "READY"},
        }

        monkeypatch.setattr(page, "load_data", lambda: None)
        monkeypatch.setattr(page, "_refresh_calendar_page", lambda: None)

        page._handle_task_board_drop(11, "in_progress", 1)

        assert service.saved_board_orders == {
            "not_started": [12],
            "in_progress": [21, 11],
        }
    finally:
        page.close()


def test_office_work_task_board_drop_refreshes_without_full_reload(qapp, monkeypatch):
    _ = qapp
    service = FakeSecretaryWorkService()
    page = OfficeWorkPage(service=service)

    try:
        page._board_lane_orders = {
            "not_started": [11, 12],
            "in_progress": [21],
            "completed": [],
        }
        page._board_task_lanes = {
            11: "not_started",
            12: "not_started",
            21: "in_progress",
        }
        page._board_tasks_by_id = {
            11: {"id": 11, "title": "Task 11", "status": "OPEN"},
            12: {"id": 12, "title": "Task 12", "status": "OPEN"},
            21: {"id": 21, "title": "Task 21", "status": "READY"},
        }

        load_calls = []
        render_calls = []
        calendar_calls = []
        monkeypatch.setattr(page, "load_data", lambda: load_calls.append(True))
        monkeypatch.setattr(page, "render_tasks", lambda: render_calls.append(True))
        monkeypatch.setattr(
            page,
            "_refresh_calendar_page",
            lambda: calendar_calls.append(True),
        )

        page._handle_task_board_drop(11, "in_progress", 1)

        assert load_calls == []
        assert render_calls == [True]
        assert calendar_calls == []
        assert service.saved_board_orders == {
            "not_started": [12],
            "in_progress": [21, 11],
        }
    finally:
        page.close()


def test_office_work_task_row_shows_overdue_triangle_icon(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        task = page.service.grouped_tasks()["overdue"][0]
        row = page._task_row(task)
        icons = row.findChildren(QLabel, "PillActionLeadingIcon")

        assert icons
    finally:
        page.close()


def test_office_work_task_row_uses_short_subtitle(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        task = page.service.grouped_tasks()["overdue"][0]
        row = page._task_row(task)
        labels = [label.text() for label in row.findChildren(QLabel)]

        assert "No due date  |  To Do  |  Passport / Interpol" in labels
        assert all(
            forbidden not in "  |  ".join(labels)
            for forbidden in [
                "Important",
                "process_automation",
                "Open Missionary",
                "Waiting",
                "Document",
                "Project",
                "Stage",
                "Automation",
            ]
        )
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


def test_task_dialog_opens_details_for_waiting_task(qapp):
    _ = qapp
    dialog = TaskDialog(
        FakeSecretaryWorkService(),
        task={
            "id": 6,
            "title": "Waiting task",
            "status": "WAITING",
            "priority": "NORMAL",
            "waiting_reason": "OTHER",
        },
    )

    try:
        assert dialog.details_widget.isHidden() is False
        assert dialog.details_button.text() == "Hide details"
        assert dialog.waiting_reason_field.isHidden() is False
        assert dialog.no_waiting_follow_up_check.isHidden() is False
    finally:
        dialog.close()


def test_task_dialog_opens_details_when_status_changes_to_waiting(qapp):
    _ = qapp
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        assert dialog.details_widget.isHidden() is True

        dialog._set_combo_data(dialog.status_combo, "WAITING")

        assert dialog.details_widget.isHidden() is False
        assert dialog.details_button.text() == "Hide details"
        assert dialog.waiting_reason_field.isHidden() is False
        assert dialog.no_waiting_follow_up_check.isHidden() is False
    finally:
        dialog.close()


def test_task_dialog_shows_recent_status_history(qapp):
    _ = qapp
    service = FakeSecretaryWorkService()
    service.status_history = [
        {
            "summary": "To Do -> Ready",
            "created_at": datetime(2026, 6, 10, 9, 30),
            "note": "",
        }
    ]
    dialog = TaskDialog(
        service,
        task={
            "id": 4,
            "title": "Review packet",
            "status": "READY",
            "priority": "NORMAL",
        },
    )

    try:
        labels = [label.text() for label in dialog.findChildren(QLabel)]

        assert "Recent Status Changes" in labels
        assert any("To Do -> Ready" in text for text in labels)
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


def test_office_work_task_row_labels_missing_follow_up(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        task = page.service.grouped_tasks()["overdue"][0].copy()
        task.update({
            "status": "WAITING",
            "waiting_reason": "OTHER",
            "waiting_reason_label": "Other waiting reason",
            "waiting_follow_up_status_label": "No follow-up date",
        })

        row = page._task_row(task)
        labels = [label.text() for label in row.findChildren(QLabel)]

        assert "No due date  |  Waiting  |  Passport / Interpol" in labels
        assert all("No follow-up date" not in text for text in labels)
    finally:
        page.close()


def test_office_work_task_row_sets_missing_follow_up(monkeypatch, qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())
    edited = []
    monkeypatch.setattr(page, "_edit_task", lambda task: edited.append(task))

    try:
        task = page.service.grouped_tasks()["overdue"][0].copy()
        task.update({
            "status": "WAITING",
            "waiting_reason": "OTHER",
            "waiting_reason_label": "Other waiting reason",
            "waiting_follow_up_date": None,
            "waiting_follow_up_status_label": "No follow-up date",
        })

        row = page._task_row(task)
        buttons = {
            button.toolTip(): button for button in row.findChildren(QToolButton)
        }

        assert set(buttons) == {
            "More actions",
            "Mark ready",
            "Mark complete",
        }

        more_menu = getattr(buttons["More actions"], "_popup_menu", None)
        assert more_menu is not None
        follow_up_action = next(
            action for action in more_menu.actions()
            if action.text() == "Set Follow-Up"
        )

        follow_up_action.trigger()

        assert edited == [task]
    finally:
        page.close()


def test_office_work_task_row_keeps_primary_actions_visible(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        task = page.service.grouped_tasks()["overdue"][0]
        row = page._task_row(task)
        buttons = {
            button.toolTip(): button for button in row.findChildren(QToolButton)
        }

        assert set(buttons) == {
            "More actions",
            "Mark ready",
            "Mark complete",
        }
        assert getattr(buttons["More actions"], "_popup_menu", None) is not None
        assert [
            action.text() for action in getattr(buttons["More actions"], "_popup_menu").actions()
        ] == ["Review", "Edit", "Archive", "Delete"]
    finally:
        page.close()


def test_office_work_ready_task_moves_needs_work_to_more_menu(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        task = page.service.grouped_tasks()["overdue"][0].copy()
        task["status"] = "READY"
        row = page._task_row(task)
        buttons = {
            button.toolTip(): button for button in row.findChildren(QToolButton)
        }

        assert set(buttons) == {
            "More actions",
            "Mark complete",
        }
        assert [
            action.text() for action in getattr(buttons["More actions"], "_popup_menu").actions()
        ] == ["Review", "Needs Work", "Edit", "Archive", "Delete"]
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

        page._summary_card_clicked(
            SimpleNamespace(button=lambda: Qt.LeftButton),
            "missing_follow_up",
        )
        assert page.task_follow_up_filter.currentData() == "missing"
        assert page.service.last_task_filters["waiting_follow_up"] == "missing"

        page._summary_card_clicked(
            SimpleNamespace(button=lambda: Qt.LeftButton),
            "open",
        )
        assert page.task_status_filter.currentData() == "OPEN"

        page._summary_card_clicked(
            SimpleNamespace(button=lambda: Qt.LeftButton),
            "upcoming_follow_up",
        )
        assert page.task_follow_up_filter.currentData() == "upcoming"
        assert page.service.last_task_filters["waiting_follow_up"] == "upcoming"

        page._set_combo_data(page.task_follow_up_filter, "upcoming")
        page.render_tasks()
        assert page.service.last_task_filters["waiting_follow_up"] == "upcoming"

        page._set_combo_data(page.task_follow_up_filter, "missing")
        page.render_tasks()
        assert page.service.last_task_filters["waiting_follow_up"] == "missing"

        page._set_combo_data(page.task_waiting_reason_filter, "MISSIONARY")
        page.render_tasks()
        assert page.service.last_task_filters["waiting_reason"] == "MISSIONARY"

        page._set_combo_data(page.task_stage_filter, "INTERPOL")
        page.render_tasks()
        assert page.service.last_task_filters["related_stage"] == "INTERPOL"

        page._set_combo_data(page.task_document_filter, "PASSPORT")
        page.render_tasks()
        assert (
            page.service.last_task_filters["related_document_type"]
            == "PASSPORT"
        )

        page._set_combo_data(page.task_source_filter, "AUTO")
        page.render_tasks()
        assert page.service.last_task_filters["automation_state"] == "AUTO"

        page._apply_task_preset("appointments")
        assert page.task_type_filter.currentData() == "APPOINTMENT"
        assert page.task_document_filter.currentData() == "ALL"
        assert page.task_source_filter.currentData() == "ALL"

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
