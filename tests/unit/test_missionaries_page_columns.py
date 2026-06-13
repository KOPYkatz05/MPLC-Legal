from ui.pages.missionaries_page import (
    COLUMN_BY_KEY,
    DEFAULT_COLUMN_KEYS,
    MISSIONARY_COLUMNS,
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
