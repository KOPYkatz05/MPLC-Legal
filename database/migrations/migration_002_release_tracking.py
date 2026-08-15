from sqlalchemy import text

from database.migrations.helpers import Migration, add_column, require_columns, require_tables


MISSIONARY_COLUMNS = {
    "row_color": "VARCHAR",
    "tracking_profile": "VARCHAR DEFAULT 'LEGAL'",
    "dynamics_contact_id": "VARCHAR",
    "dynamics_row_checksum": "VARCHAR",
    "dynamics_modified_at": "DATETIME",
    "dynamics_status": "VARCHAR",
    "release_date": "DATE",
    "home_address": "TEXT",
    "father_name": "VARCHAR",
    "mother_name": "VARCHAR",
    "father_first_name_override": "VARCHAR",
    "mother_first_name_override": "VARCHAR",
}


def upgrade(connection):
    for column, definition in MISSIONARY_COLUMNS.items():
        add_column(connection, "missionaries", column, definition)
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS dynamics_roster_imports ("
            "id INTEGER PRIMARY KEY, preview_id VARCHAR NOT NULL UNIQUE, "
            "status VARCHAR NOT NULL DEFAULT 'PREVIEW', filename VARCHAR NOT NULL, "
            "filename_timestamp VARCHAR, file_sha256 VARCHAR NOT NULL, "
            "dynamics_modified_at DATETIME, summary_json TEXT, applying_device VARCHAR, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME)"
        )
    )


def validate(connection):
    require_columns(connection, "missionaries", MISSIONARY_COLUMNS)
    require_tables(connection, {"dynamics_roster_imports"})
    require_columns(
        connection,
        "dynamics_roster_imports",
        {"id", "preview_id", "status", "filename", "file_sha256"},
    )


MIGRATION = Migration(
    version=2,
    name="release_and_dynamics_tracking",
    checksum="schema-2-release-tracking-v1",
    upgrade=upgrade,
    validate=validate,
)

