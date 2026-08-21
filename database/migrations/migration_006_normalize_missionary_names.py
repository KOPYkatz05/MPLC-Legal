from sqlalchemy import text

from database.migrations.helpers import (
    Migration,
    MigrationValidationError,
    require_columns,
)
from utils.names import normalize_person_name


def upgrade(connection):
    require_columns(connection, "missionaries", {"id", "full_name"})
    rows = connection.execute(
        text("SELECT id, full_name FROM missionaries WHERE full_name IS NOT NULL")
    ).all()
    for missionary_id, full_name in rows:
        normalized = normalize_person_name(full_name)
        if normalized != full_name:
            connection.execute(
                text(
                    "UPDATE missionaries SET full_name = :full_name WHERE id = :id"
                ),
                {"id": missionary_id, "full_name": normalized},
            )


def validate(connection):
    require_columns(connection, "missionaries", {"id", "full_name"})
    invalid = [
        missionary_id
        for missionary_id, full_name in connection.execute(
            text("SELECT id, full_name FROM missionaries WHERE full_name IS NOT NULL")
        ).all()
        if normalize_person_name(full_name) != full_name
    ]
    if invalid:
        raise MigrationValidationError(
            "Missionary names still contain leading, trailing, or repeated whitespace"
        )


MIGRATION = Migration(
    version=6,
    name="normalize_missionary_names",
    checksum="data-6-normalize-missionary-name-whitespace-v1",
    upgrade=upgrade,
    validate=validate,
)
