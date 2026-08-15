from dataclasses import dataclass

from sqlalchemy import inspect, text


class MigrationValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    upgrade: object
    validate: object


def table_names(connection):
    return set(inspect(connection).get_table_names())


def column_names(connection, table):
    if table not in table_names(connection):
        return set()
    return {column["name"] for column in inspect(connection).get_columns(table)}


def index_names(connection, table):
    if table not in table_names(connection):
        return set()
    return {index["name"] for index in inspect(connection).get_indexes(table)}


def add_column(connection, table, column, definition):
    if table not in table_names(connection):
        raise MigrationValidationError(f"Required table is missing: {table}")
    if column not in column_names(connection, table):
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def require_tables(connection, required):
    missing = set(required) - table_names(connection)
    if missing:
        raise MigrationValidationError(
            "Required database tables are missing: " + ", ".join(sorted(missing))
        )


def require_columns(connection, table, required):
    missing = set(required) - column_names(connection, table)
    if missing:
        raise MigrationValidationError(
            f"Required columns are missing from {table}: "
            + ", ".join(sorted(missing))
        )


def require_indexes(connection, table, required):
    missing = set(required) - index_names(connection, table)
    if missing:
        raise MigrationValidationError(
            f"Required indexes are missing from {table}: "
            + ", ".join(sorted(missing))
        )

