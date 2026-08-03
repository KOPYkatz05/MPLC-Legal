from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from ui.pages.missionaries_page import (
    COLUMN_BY_KEY,
    CreateMissionaryGroupDialog,
    DEFAULT_COLUMN_KEYS,
    GROUP_EDIT_ACTION,
    MISSIONARY_COLUMNS,
    MIN_TABLE_COLUMN_WIDTH,
    MissionariesPage,
    create_missionaries_pill_button,
    _last_name_first,
    _format_date,
    _format_datetime,
    _sort_value_for_column,
)


def _table_text(page, row, column):
    return page.table.model().index(row, column).data(Qt.DisplayRole)


def _select_table_rows(page, *rows):
    selection_model = page.table.selectionModel()
    for row in rows:
        selection_model.select(
            page.table.model().index(row, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )


def test_missionary_table_includes_detail_page_fields():
    keys = {column.key for column in MISSIONARY_COLUMNS}

    assert "date_of_birth" in keys
    assert "carnet_number" in keys
    assert "tramite_usuario" in keys
    assert "tramite_contrasena" in keys
    assert "last_name_first" in keys
    assert "folder_path" not in keys


def test_edit_columns_includes_dynamics_roster_fields():
    keys = {column.key for column in MISSIONARY_COLUMNS}

    assert {
        "tracking_profile",
        "dynamics_status",
        "dynamics_contact_id",
        "release_date",
        "home_address",
        "father_name",
        "mother_name",
        "father_first_name_override",
        "mother_first_name_override",
        "dynamics_modified_at",
    } <= keys


def test_dynamics_columns_render_imported_values():
    missionary = SimpleNamespace(
        tracking_profile="PERUVIAN_DNI",
        dynamics_status="In-field",
        dynamics_contact_id="contact-guid",
        release_date=date(2027, 1, 15),
        home_address="123 Home Street",
        father_name="Carlos Example",
        mother_name="Maria Example",
        father_first_name_override="Carl",
        mother_first_name_override="Mary",
        dynamics_modified_at=None,
    )

    assert COLUMN_BY_KEY["tracking_profile"].getter(missionary) == "PERUVIAN_DNI"
    assert COLUMN_BY_KEY["dynamics_status"].getter(missionary) == "In-field"
    assert COLUMN_BY_KEY["dynamics_contact_id"].getter(missionary) == "contact-guid"
    assert COLUMN_BY_KEY["release_date"].getter(missionary) == "15/JAN/2027"
    assert COLUMN_BY_KEY["home_address"].getter(missionary) == "123 Home Street"
    assert COLUMN_BY_KEY["father_name"].getter(missionary) == "Carlos Example"
    assert COLUMN_BY_KEY["mother_name"].getter(missionary) == "Maria Example"


def test_edit_columns_popup_receives_dynamics_roster_columns():
    page = MissionariesPage.__new__(MissionariesPage)
    page._selected_tab = "active"

    keys = {column.key for column in page._column_dialog_columns()}

    assert "release_date" in keys
    assert "tracking_profile" in keys
    assert "dynamics_status" in keys
    assert "home_address" in keys
    assert "father_name" in keys
    assert "mother_name" in keys


def test_default_visible_columns_still_focus_on_core_summary():
    assert "folder_path" not in DEFAULT_COLUMN_KEYS
    assert "date_of_birth" not in DEFAULT_COLUMN_KEYS
    assert "carnet_number" not in DEFAULT_COLUMN_KEYS
    assert "tramite_usuario" not in DEFAULT_COLUMN_KEYS
    assert "tramite_contrasena" not in DEFAULT_COLUMN_KEYS
    assert "last_name_first" not in DEFAULT_COLUMN_KEYS
    assert "missionary_id" in DEFAULT_COLUMN_KEYS
    assert "full_name" in DEFAULT_COLUMN_KEYS
    assert "nationality" in DEFAULT_COLUMN_KEYS
    assert "passport_number" in DEFAULT_COLUMN_KEYS


def test_column_lookup_ignores_removed_folder_path():
    assert "folder_path" not in COLUMN_BY_KEY


def test_last_name_first_formats_common_name_lengths():
    assert _last_name_first("") == ""
    assert _last_name_first("Madonna") == "Madonna"
    assert _last_name_first("James Smith") == "Smith, James"
    assert (
        _last_name_first("James William VanOrden")
        == "VanOrden, James William"
    )
    assert (
        _last_name_first("Maria Fernanda Lopez Garcia")
        == "Lopez Garcia, Maria Fernanda"
    )
    assert (
        _last_name_first("  Maria   Fernanda   Lopez   Garcia  ")
        == "Lopez Garcia, Maria Fernanda"
    )


def test_last_name_first_column_prefers_preferred_name_override():
    column = COLUMN_BY_KEY["last_name_first"]

    missionary = SimpleNamespace(
        full_name="Maria Fernanda Lopez Garcia",
        preferred_name="Garcia Lopez, Maria Fernanda",
    )

    assert column.getter(missionary) == "Garcia Lopez, Maria Fernanda"


def test_last_name_first_column_falls_back_to_full_name():
    column = COLUMN_BY_KEY["last_name_first"]

    missionary = SimpleNamespace(
        full_name="Maria Fernanda Lopez Garcia",
        preferred_name="",
    )

    assert column.getter(missionary) == "Lopez Garcia, Maria Fernanda"


def test_temporary_group_filter_label_is_marked():
    label = MissionariesPage._group_filter_label({
        "name": "Temporary - Prorroga batch",
        "member_count": 3,
        "group_type": "TEMPORARY_AUTOMATION",
    })

    assert label == "Temporary - Prorroga batch (3)  [Temporary]"


def test_date_columns_sort_by_iso_date_values():
    missionary = SimpleNamespace(arrival_date=date(2026, 1, 5))

    sort_value = _sort_value_for_column(
        COLUMN_BY_KEY["arrival_date"],
        missionary,
        "05/01/2026",
    )

    assert sort_value == "2026-01-05"


def test_table_dates_use_uppercase_english_month_abbreviations():
    assert _format_date(date(2006, 5, 12)) == "12/MAY/2006"
    assert _format_date("2026-01-05") == "05/JAN/2026"
    assert _format_datetime("2026-09-07T14:30:00") == (
        "07/SEP/2026 14:30"
    )


def test_missionaries_action_pill_does_not_latch_checked(qapp):
    button = create_missionaries_pill_button("Action")
    button.show()

    try:
        assert not button.isCheckable()
        QTest.mouseClick(button, Qt.LeftButton)
        assert not button.isChecked()
    finally:
        button.close()


def test_column_widths_balance_to_available_space():
    class FakeViewport:
        def __init__(self, width):
            self._width = width

        def width(self):
            return self._width

    class FakeTable:
        def __init__(self, width):
            self._viewport = FakeViewport(width)

        def viewport(self):
            return self._viewport

        def width(self):
            return self._viewport.width()

    page = SimpleNamespace(table=FakeTable(360))

    widths = MissionariesPage._balanced_default_widths(
        page,
        {
            "missionary_id": 120,
            "full_name": 260,
            "nationality": 120,
        },
    )

    assert sum(widths.values()) == 360
    assert min(widths.values()) >= MIN_TABLE_COLUMN_WIDTH


def test_missionaries_page_sorts_date_columns_chronologically(
    monkeypatch,
    qapp,
):
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Later Arrival",
            preferred_name="",
            nationality="Peru",
            current_stage="",
            arrival_date=date(2026, 2, 1),
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Earlier Arrival",
            preferred_name="",
            nationality="Peru",
            current_stage="",
            arrival_date=date(2026, 1, 15),
        ),
    ]

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return missionaries

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            _ = default
            return ["missionary_id", "arrival_date"]

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page.table.sortByColumn(2, Qt.AscendingOrder)

        assert _table_text(page, 0, 2) == "15/JAN/2026"
        assert _table_text(page, 1, 2) == "01/FEB/2026"
    finally:
        page.close()


def test_missionaries_page_group_filter_shows_only_members(monkeypatch, qapp):
    _ = qapp
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Group Member",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="",
            tramite_usuario="",
            tramite_contrasena="",
            arrival_date=None,
            visa_expiration=None,
            passport_expiration=None,
            residency_expiration=None,
            prorroga_expiration=None,
            carnet_issue_date=None,
            cancelacion_date=None,
            interpol_appointment_date=None,
            biometric_appointment_date=None,
            pickup_appointment_date=None,
            date_of_birth=None,
            notes="",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Outside Group",
            preferred_name="",
            nationality="Chile",
            passport_number="B2",
            current_stage="",
            tramite_usuario="",
            tramite_contrasena="",
            arrival_date=None,
            visa_expiration=None,
            passport_expiration=None,
            residency_expiration=None,
            prorroga_expiration=None,
            carnet_issue_date=None,
            cancelacion_date=None,
            interpol_appointment_date=None,
            biometric_appointment_date=None,
            pickup_appointment_date=None,
            date_of_birth=None,
            notes="",
        ),
    ]

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return missionaries

    class FakeGroupService:
        def list_groups(self):
            return [
                {
                    "id": 33,
                    "name": "Llegadas",
                    "missionary_ids": [1],
                    "member_count": 1,
                }
            ]

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            return default

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page.group_filter.setCurrentIndex(page.group_filter.findData(33))

        assert page.table.model().rowCount() == 1
        assert _table_text(page, 0, 1) == "Group Member"
    finally:
        page.close()


def test_missionaries_page_search_includes_last_name_first(monkeypatch, qapp):
    _ = qapp
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Maria Fernanda Lopez Garcia",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="James William VanOrden",
            preferred_name="",
            nationality="USA",
            passport_number="B2",
            current_stage="",
        ),
    ]

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return missionaries

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            return default

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page.search_input.setText("Lopez Garcia")
        QTest.qWait(150)

        assert page.table.model().rowCount() == 1
        assert _table_text(page, 0, 1) == "Maria Fernanda Lopez Garcia"
    finally:
        page.close()


def test_column_export_uses_current_filtered_view(monkeypatch, qapp):
    _ = qapp
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Group Member",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="INTERPOL",
            tramite_usuario="",
            tramite_contrasena="",
            arrival_date=None,
            visa_expiration=None,
            passport_expiration=None,
            residency_expiration=None,
            prorroga_expiration=None,
            carnet_issue_date=None,
            cancelacion_date=None,
            interpol_appointment_date=None,
            biometric_appointment_date=None,
            pickup_appointment_date=None,
            date_of_birth=None,
            notes="",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Outside Group",
            preferred_name="",
            nationality="Chile",
            passport_number="B2",
            current_stage="INTERPOL",
            tramite_usuario="",
            tramite_contrasena="",
            arrival_date=None,
            visa_expiration=None,
            passport_expiration=None,
            residency_expiration=None,
            prorroga_expiration=None,
            carnet_issue_date=None,
            cancelacion_date=None,
            interpol_appointment_date=None,
            biometric_appointment_date=None,
            pickup_appointment_date=None,
            date_of_birth=None,
            notes="",
        ),
    ]

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return missionaries

    class FakeGroupService:
        def list_groups(self):
            return [
                {
                    "id": 33,
                    "name": "Llegadas",
                    "missionary_ids": [1],
                    "member_count": 1,
                }
            ]

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            return default

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    exported = {}

    class FakeExportService:
        def export_missionaries_to_excel(self, exported_missionaries, path, columns=None):
            exported["names"] = [
                missionary.full_name
                for missionary in exported_missionaries
            ]
            exported["path"] = path
            exported["columns"] = columns
            return True

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(page_module, "ExportService", FakeExportService)
    monkeypatch.setattr(
        page_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("missionaries-export-test.xlsx", ""),
    )
    monkeypatch.setattr(
        page_module,
        "show_message",
        lambda *args, **kwargs: None,
    )

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page.group_filter.setCurrentIndex(page.group_filter.findData(33))
        page._export_excel()

        assert exported["names"] == ["Group Member"]
    finally:
        page.close()


def test_export_menu_uses_actions_compatible_with_fluent_menu(monkeypatch, qapp):
    _ = qapp
    from ui.pages import missionaries_page as page_module

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return []

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            return default

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    shown_menus = []

    class FakeMenu:
        def __init__(self):
            self.actions = []

        def addAction(self, action):
            assert hasattr(action, "icon")
            assert hasattr(action, "text")
            self.actions.append(action)

        def exec(self, pos):
            _ = pos
            shown_menus.append(self)

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(page_module, "create_menu", lambda *args: FakeMenu())

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page._show_export_menu()

        assert shown_menus
        assert [action.text() for action in shown_menus[0].actions] == [
            "Export Columns",
            "Full Export",
        ]
    finally:
        page.close()


def test_edit_group_dialog_updates_existing_members(qapp):
    _ = qapp
    missionaries = [
        SimpleNamespace(id=1, full_name="Current Member"),
        SimpleNamespace(id=2, full_name="New Member"),
    ]

    class FakeGroupService:
        def __init__(self):
            self.updated = None

        def update_group(self, group_id, **payload):
            self.updated = (group_id, payload)
            return {"id": group_id, **payload}

    service = FakeGroupService()
    dialog = CreateMissionaryGroupDialog(
        service,
        missionaries,
        group={
            "id": 33,
            "name": "Llegadas",
            "description": "June arrivals",
            "missionary_ids": [1],
        },
    )

    try:
        assert dialog.name_input.text() == "Llegadas"
        assert dialog.member_list.item(0).checkState() == Qt.Checked
        assert dialog.member_list.item(1).checkState() == Qt.Unchecked

        dialog.member_list.item(0).setCheckState(Qt.Unchecked)
        dialog.member_list.item(1).setCheckState(Qt.Checked)
        dialog._save()

        assert service.updated == (
            33,
            {
                "name": "Llegadas",
                "description": "June arrivals",
                "missionary_ids": [2],
            },
        )
    finally:
        dialog.close()


def test_create_group_dialog_preselects_initial_members(qapp):
    _ = qapp
    missionaries = [
        SimpleNamespace(id=1, full_name="Selected One"),
        SimpleNamespace(id=2, full_name="Not Selected"),
        SimpleNamespace(id=3, full_name="Selected Three"),
    ]

    dialog = CreateMissionaryGroupDialog(
        SimpleNamespace(),
        missionaries,
        selected_missionary_ids=[1, 3],
    )

    try:
        assert dialog.member_list.item(0).checkState() == Qt.Checked
        assert dialog.member_list.item(1).checkState() == Qt.Unchecked
        assert dialog.member_list.item(2).checkState() == Qt.Checked
    finally:
        dialog.close()


def test_create_group_uses_selected_table_rows(monkeypatch, qapp):
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Selected One",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="INTERPOL",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Selected Two",
            preferred_name="",
            nationality="Chile",
            passport_number="B2",
            current_stage="INTERPOL",
        ),
    ]

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return missionaries

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            _ = default
            return ["missionary_id", "full_name"]

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    captured = {}

    class FakeCreateGroupDialog:
        saved_group = None

        def __init__(
            self,
            group_service,
            dialog_missionaries,
            parent=None,
            group=None,
            selected_missionary_ids=None,
        ):
            captured["ids"] = list(selected_missionary_ids or [])
            captured["missionaries"] = dialog_missionaries

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(
        page_module,
        "CreateMissionaryGroupDialog",
        FakeCreateGroupDialog,
    )

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        _select_table_rows(page, 0, 1)
        page._create_group()

        assert captured["ids"] == [1, 2]
        assert captured["missionaries"] == missionaries
    finally:
        page.close()


def test_batch_actions_archive_selected_rows(monkeypatch, qapp):
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Archive One",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="INTERPOL",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Archive Two",
            preferred_name="",
            nationality="Chile",
            passport_number="B2",
            current_stage="PRORROGA",
        ),
    ]

    class FakeMissionaryService:
        def __init__(self):
            self.archived_ids = []

        def get_all_missionaries(self):
            return missionaries

        def archive_missionaries(self, missionary_ids):
            self.archived_ids = list(missionary_ids)

        def archive_missionaries_as_group(self, missionary_ids, group_name):
            _ = missionary_ids
            _ = group_name

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            _ = default
            return ["missionary_id", "full_name"]

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    shown_actions = []

    class FakeMenu:
        def __init__(self):
            self.actions = []

        def addAction(self, action):
            self.actions.append(action)

        def exec(self, pos):
            _ = pos
            shown_actions.extend(action.text() for action in self.actions)
            archive_action = next(
                action
                for action in self.actions
                if action.text() == "Archive"
            )
            archive_action.trigger()

    class FakeBatchArchiveDialog:
        archive_mode = "individual"
        group_name = ""

        def __init__(self, selected_count, parent=None):
            self.selected_count = selected_count

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(page_module, "create_menu", lambda *args: FakeMenu())
    monkeypatch.setattr(
        page_module,
        "BatchArchiveDialog",
        FakeBatchArchiveDialog,
    )

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        _select_table_rows(page, 0, 1)
        page._batch_actions()

        assert shown_actions == ["Advance Stage", "Archive"]
        assert page.missionary_service.archived_ids == [1, 2]
    finally:
        page.close()


def test_batch_actions_group_archives_selected_rows(monkeypatch, qapp):
    from ui.pages import missionaries_page as page_module

    missionaries = [
        SimpleNamespace(
            id=1,
            missionary_code="1",
            full_name="Transfer One",
            preferred_name="",
            nationality="Peru",
            passport_number="A1",
            current_stage="INTERPOL",
        ),
        SimpleNamespace(
            id=2,
            missionary_code="2",
            full_name="Transfer Two",
            preferred_name="",
            nationality="Chile",
            passport_number="B2",
            current_stage="PRORROGA",
        ),
    ]

    class FakeMissionaryService:
        def __init__(self):
            self.group_archive = None

        def get_all_missionaries(self):
            return missionaries

        def archive_missionaries(self, missionary_ids):
            _ = missionary_ids

        def archive_missionaries_as_group(self, missionary_ids, group_name):
            self.group_archive = (list(missionary_ids), group_name)
            return "Archive/2026/Transfers.zip"

    class FakeGroupService:
        def list_groups(self):
            return []

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            _ = default
            return ["missionary_id", "full_name"]

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    class FakeMenu:
        def __init__(self):
            self.actions = []

        def addAction(self, action):
            self.actions.append(action)

        def exec(self, pos):
            _ = pos
            archive_action = next(
                action
                for action in self.actions
                if action.text() == "Archive"
            )
            archive_action.trigger()

    class FakeBatchArchiveDialog:
        archive_mode = "group"
        group_name = "Transfers"

        def __init__(self, selected_count, parent=None):
            self.selected_count = selected_count

        def exec(self):
            return QDialog.Accepted

    messages = []

    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(page_module, "create_menu", lambda *args: FakeMenu())
    monkeypatch.setattr(
        page_module,
        "BatchArchiveDialog",
        FakeBatchArchiveDialog,
    )
    monkeypatch.setattr(
        page_module,
        "show_message",
        lambda *args, **kwargs: messages.append(args),
    )

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        _select_table_rows(page, 0, 1)
        page._batch_actions()

        assert page.missionary_service.group_archive == (
            [1, 2],
            "Transfers",
        )
        assert messages
    finally:
        page.close()


def test_group_dropdown_includes_edit_action(monkeypatch, qapp):
    from ui.pages import missionaries_page as page_module

    missionary = SimpleNamespace(
        id=1,
        missionary_code="1",
        full_name="Group Member",
        preferred_name="",
        nationality="Peru",
        passport_number="A1",
        current_stage="",
        tramite_usuario="",
        tramite_contrasena="",
        arrival_date=None,
        visa_expiration=None,
        passport_expiration=None,
        residency_expiration=None,
        prorroga_expiration=None,
        carnet_issue_date=None,
        cancelacion_date=None,
        interpol_appointment_date=None,
        biometric_appointment_date=None,
        pickup_appointment_date=None,
        date_of_birth=None,
        notes="",
    )

    class FakeMissionaryService:
        def get_all_missionaries(self):
            return [missionary]

    class FakeGroupService:
        def list_groups(self):
            return [
                {
                    "id": 33,
                    "name": "Llegadas",
                    "missionary_ids": [1],
                    "member_count": 1,
                }
            ]

    class FakeSettingsService:
        def get_missionaries_table_columns(self, default):
            return default

        def set_missionaries_table_columns(self, keys):
            _ = keys

        def get_missionaries_table_column_widths(self):
            return {}

        def set_missionaries_table_column_widths(self, widths):
            _ = widths

    edited_group_ids = []
    monkeypatch.setattr(page_module, "MissionaryService", FakeMissionaryService)
    monkeypatch.setattr(page_module, "MissionaryGroupService", FakeGroupService)
    monkeypatch.setattr(
        page_module.MissionariesPage,
        "_edit_group_by_id",
        lambda self, group_id: edited_group_ids.append(group_id),
    )

    window = SimpleNamespace(
        settings_service=FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)

    try:
        page.group_filter.setCurrentIndex(page.group_filter.findData(33))
        edit_index = page.group_filter.findData(GROUP_EDIT_ACTION)

        assert edit_index >= 0

        page.group_filter.setCurrentIndex(edit_index)
        qapp.processEvents()

        assert page.group_filter.currentData() == 33
        assert edited_group_ids == [33]
    finally:
        page.close()
