from sqlalchemy import text

from database.migrations.helpers import (
    Migration,
    MigrationValidationError,
    add_column,
    require_columns,
)


def upgrade(connection):
    add_column(connection, "missionaries", "last_entry_date", "DATE")
    connection.execute(
        text(
            "UPDATE missionaries SET last_entry_date = arrival_date "
            "WHERE last_entry_date IS NULL AND arrival_date IS NOT NULL"
        )
    )


def validate(connection):
    require_columns(connection, "missionaries", {"arrival_date", "last_entry_date"})
    missing_backfills = connection.execute(
        text(
            "SELECT COUNT(*) FROM missionaries "
            "WHERE arrival_date IS NOT NULL AND last_entry_date IS NULL"
        )
    ).scalar_one()
    if missing_backfills:
        raise MigrationValidationError(
            "Missionary last entry dates were not backfilled from arrival dates"
        )


MIGRATION = Migration(
    version=5,
    name="last_entry_date",
    checksum="schema-5-last-entry-date-v1",
    upgrade=upgrade,
    validate=validate,
)
