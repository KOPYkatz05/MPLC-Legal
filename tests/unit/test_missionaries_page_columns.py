from types import SimpleNamespace

from ui.pages.missionaries_page import (
    COLUMN_BY_KEY,
    DEFAULT_COLUMN_KEYS,
    MISSIONARY_COLUMNS,
    MissionariesPage,
)


def test_missionary_table_includes_detail_page_fields():
    keys = {column.key for column in MISSIONARY_COLUMNS}

    assert "date_of_birth" in keys
    assert "tramite_usuario" in keys
    assert "tramite_contrasena" in keys
    assert "folder_path" not in keys


def test_default_visible_columns_still_focus_on_core_summary():
    assert "folder_path" not in DEFAULT_COLUMN_KEYS
    assert "date_of_birth" not in DEFAULT_COLUMN_KEYS
    assert "tramite_usuario" not in DEFAULT_COLUMN_KEYS
    assert "tramite_contrasena" not in DEFAULT_COLUMN_KEYS
    assert "missionary_id" in DEFAULT_COLUMN_KEYS
    assert "full_name" in DEFAULT_COLUMN_KEYS
    assert "nationality" in DEFAULT_COLUMN_KEYS
    assert "passport_number" in DEFAULT_COLUMN_KEYS


def test_column_lookup_ignores_removed_folder_path():
    assert "folder_path" not in COLUMN_BY_KEY


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

        assert page.table.rowCount() == 1
        assert page.table.item(0, 1).text() == "Group Member"
    finally:
        page.close()
