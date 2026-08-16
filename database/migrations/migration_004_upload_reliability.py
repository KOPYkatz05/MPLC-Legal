from sqlalchemy import text

from database.migrations.helpers import (
    Migration,
    MigrationValidationError,
    add_column,
    require_columns,
    require_indexes,
)


DOCUMENT_COLUMNS = {
    "upload_id": "VARCHAR",
    "content_sha256": "VARCHAR",
    "file_size": "INTEGER",
    "supersedes_document_id": "INTEGER REFERENCES documents(id) ON DELETE SET NULL",
    "post_processing_status": "VARCHAR NOT NULL DEFAULT 'NOT_REQUIRED'",
    "post_processing_error": "TEXT",
    "post_processing_updated_fields": "TEXT",
    "storage_relative_path": "TEXT",
}

MISSIONARY_COLUMNS = {
    "folder_relative_path": "TEXT",
}


def upgrade(connection):
    for column, definition in MISSIONARY_COLUMNS.items():
        add_column(connection, "missionaries", column, definition)
    for column, definition in DOCUMENT_COLUMNS.items():
        add_column(connection, "documents", column, definition)
    connection.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_upload_id ON documents(upload_id)")
    )
    require_columns(
        connection,
        "residency_events",
        {"id", "missionary_id", "event_type", "sequence_number", "status"},
    )
    connection.execute(
        text(
            "UPDATE residency_events SET status = 'SUPERSEDED', sequence_number = -id "
            "WHERE id NOT IN (SELECT MAX(id) FROM residency_events "
            "GROUP BY missionary_id, event_type, sequence_number)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_residency_event_identity "
            "ON residency_events(missionary_id, event_type, sequence_number)"
        )
    )


def validate(connection):
    require_columns(connection, "missionaries", MISSIONARY_COLUMNS)
    require_columns(connection, "documents", DOCUMENT_COLUMNS)
    require_indexes(connection, "documents", {"uq_documents_upload_id"})
    require_indexes(connection, "residency_events", {"uq_residency_event_identity"})
    duplicates = connection.execute(
        text(
            "SELECT COUNT(*) FROM (SELECT 1 FROM residency_events "
            "GROUP BY missionary_id, event_type, sequence_number HAVING COUNT(*) > 1)"
        )
    ).scalar_one()
    if duplicates:
        raise MigrationValidationError(
            "Duplicate residency event identities remain after schema migration"
        )


MIGRATION = Migration(
    version=4,
    name="durable_uploads_and_residency_identity",
    checksum="schema-4-upload-reliability-v1",
    upgrade=upgrade,
    validate=validate,
)
