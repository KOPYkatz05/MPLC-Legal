from database.migrations.helpers import Migration, add_column, require_columns


def upgrade(connection):
    add_column(connection, "missionaries", "dni_number", "TEXT")


def validate(connection):
    require_columns(connection, "missionaries", {"dni_number"})


MIGRATION = Migration(
    version=3,
    name="dni_tracking",
    checksum="schema-3-dni-tracking-v1",
    upgrade=upgrade,
    validate=validate,
)

