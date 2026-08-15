from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from database.migrations import MIGRATIONS
from database.migrations.helpers import MigrationValidationError
from version import APP_VERSION, SCHEMA_VERSION


class DatabaseMigrationError(RuntimeError):
    pass


class DatabaseVersionTooNewError(DatabaseMigrationError):
    pass


class MigrationGapError(DatabaseMigrationError):
    pass


class MigrationChecksumMismatchError(DatabaseMigrationError):
    pass


class MigrationExecutionError(DatabaseMigrationError):
    pass


@dataclass(frozen=True)
class MigrationResult:
    starting_version: int
    ending_version: int
    applied: tuple

    @property
    def migration_required(self):
        return self.starting_version < self.ending_version


def _registry(target_version=SCHEMA_VERSION):
    selected = tuple(migration for migration in MIGRATIONS if migration.version <= target_version)
    versions = [migration.version for migration in selected]
    expected = list(range(1, target_version + 1))
    if versions != expected:
        raise MigrationGapError(
            f"Migration registry must contain versions 1 through {target_version}; "
            f"found {versions}"
        )
    return selected


def _table_exists(connection, table):
    return table in inspect(connection).get_table_names()


def _metadata_version(connection):
    if not _table_exists(connection, "app_metadata"):
        return 0
    value = connection.execute(
        text("SELECT value FROM app_metadata WHERE key = 'schema_version'")
    ).scalar_one_or_none()
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError) as exc:
        raise MigrationValidationError(
            f"Stored schema version is invalid: {value!r}"
        ) from exc


def get_current_version(engine):
    with engine.connect() as connection:
        return _metadata_version(connection)


def migration_required(engine, target_version=SCHEMA_VERSION):
    with engine.connect() as connection:
        current = _metadata_version(connection)
        has_ledger = _table_exists(connection, "schema_migrations")
    if current > target_version:
        raise DatabaseVersionTooNewError(
            f"Database schema {current} is newer than supported schema {target_version}"
        )
    # Creating the ledger for a released pre-ledger database is itself a
    # controlled database change and therefore receives the same backup gate.
    return current < target_version or not has_ledger


def _ensure_tracking_tables(connection):
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS app_metadata ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "checksum TEXT NOT NULL, app_version TEXT NOT NULL, "
            "applied_at DATETIME NOT NULL)"
        )
    )


def _ledger(connection):
    if not _table_exists(connection, "schema_migrations"):
        return {}
    return {
        row.version: row
        for row in connection.execute(
            text(
                "SELECT version, name, checksum, app_version, applied_at "
                "FROM schema_migrations ORDER BY version"
            )
        ).all()
    }


def _record(connection, migration):
    connection.execute(
        text(
            "INSERT INTO schema_migrations "
            "(version, name, checksum, app_version, applied_at) "
            "VALUES (:version, :name, :checksum, :app_version, :applied_at)"
        ),
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "app_version": APP_VERSION,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _record_schema_version(connection, version):
    connection.execute(
        text(
            "INSERT INTO app_metadata (key, value) VALUES ('schema_version', :version) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"version": str(version)},
    )


def _validate_ledger(ledger, registry, current_version):
    ledger_versions = sorted(ledger)
    if ledger_versions and ledger_versions != list(range(1, ledger_versions[-1] + 1)):
        raise MigrationGapError(
            f"Migration ledger has a gap: found {ledger_versions}"
        )
    if ledger_versions and ledger_versions[-1] > current_version:
        raise MigrationGapError(
            f"Migration ledger version {ledger_versions[-1]} is ahead of "
            f"recorded schema version {current_version}"
        )
    unexpected = set(ledger) - {migration.version for migration in registry}
    if unexpected:
        raise MigrationGapError(
            "Migration ledger contains unsupported versions: "
            + ", ".join(str(version) for version in sorted(unexpected))
        )
    for migration in registry:
        row = ledger.get(migration.version)
        if row is None:
            if migration.version <= current_version:
                continue
            break
        if row.name != migration.name or row.checksum != migration.checksum:
            raise MigrationChecksumMismatchError(
                f"Applied migration {migration.version} no longer matches "
                f"{migration.name}"
            )


def initialize_fresh_database(engine, create_schema):
    registry = _registry()
    create_schema()
    with engine.begin() as connection:
        _ensure_tracking_tables(connection)
        for migration in registry:
            migration.validate(connection)
            _record(connection, migration)
        _record_schema_version(connection, SCHEMA_VERSION)
    return MigrationResult(0, SCHEMA_VERSION, tuple(range(1, SCHEMA_VERSION + 1)))


def run_migrations(engine, target_version=SCHEMA_VERSION):
    registry = _registry(target_version)
    with engine.connect() as connection:
        current = _metadata_version(connection)
    if current > target_version:
        raise DatabaseVersionTooNewError(
            f"Database schema {current} is newer than supported schema {target_version}"
        )
    if current < 1:
        raise MigrationValidationError(
            "Existing database has no trustworthy schema version"
        )

    # Adopt a pre-ledger released database only after validating every contract
    # that its recorded version claims to satisfy.
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _ensure_tracking_tables(connection)
            ledger = _ledger(connection)
            _validate_ledger(ledger, registry, current)
            for migration in registry[:current]:
                migration.validate(connection)
                if migration.version not in ledger:
                    _record(connection, migration)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    applied = []
    for migration in registry[current:]:
        try:
            with engine.connect() as connection:
                # Python's legacy sqlite3 transaction mode does not begin a
                # transaction for DDL. Start one explicitly so ALTER TABLE and
                # its data/index work roll back as one migration.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    migration.upgrade(connection)
                    migration.validate(connection)
                    _record(connection, migration)
                    _record_schema_version(connection, migration.version)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except Exception as exc:
            if isinstance(exc, DatabaseMigrationError):
                raise
            raise MigrationExecutionError(
                f"Migration {migration.version} ({migration.name}) failed"
            ) from exc
        applied.append(migration.version)

    return MigrationResult(current, target_version, tuple(applied))
