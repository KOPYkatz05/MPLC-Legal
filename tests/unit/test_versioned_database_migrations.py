from sqlalchemy import create_engine, inspect, text

import database.migrations.runner as runner
from database.migrations.helpers import MigrationValidationError
from database.migrations.runner import (
    MigrationChecksumMismatchError,
    MigrationExecutionError,
    initialize_fresh_database,
    migration_required,
    run_migrations,
)
from database.base import Base
from version import SCHEMA_VERSION


def _load_models():
    import database.models.appointment  # noqa: F401
    import database.models.document  # noqa: F401
    import database.models.missionary  # noqa: F401
    import database.models.residency_event  # noqa: F401
    import database.models.secretary_work  # noqa: F401
    import database.models.stage_history  # noqa: F401
    import database.models.workflow  # noqa: F401


def _released_schema_engine(schema_version=3, include_residency=True):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO app_metadata VALUES ('schema_version', :version)"),
            {"version": str(schema_version)},
        )
        missionary_columns = [
            "id INTEGER PRIMARY KEY",
            "full_name VARCHAR",
            "current_stage VARCHAR",
        ]
        if schema_version >= 2:
            missionary_columns.extend(
                [
                    "row_color VARCHAR",
                    "tracking_profile VARCHAR",
                    "dynamics_contact_id VARCHAR",
                    "dynamics_row_checksum VARCHAR",
                    "dynamics_modified_at DATETIME",
                    "dynamics_status VARCHAR",
                    "release_date DATE",
                    "home_address TEXT",
                    "father_name VARCHAR",
                    "mother_name VARCHAR",
                    "father_first_name_override VARCHAR",
                    "mother_first_name_override VARCHAR",
                ]
            )
        if schema_version >= 3:
            missionary_columns.append("dni_number TEXT")
        connection.execute(
            text(
                "CREATE TABLE missionaries (" + ", ".join(missionary_columns) + ")"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, missionary_id INTEGER, "
                "document_type VARCHAR, file_path VARCHAR)"
            )
        )
        connection.execute(text("CREATE TABLE workflow_stages (id INTEGER PRIMARY KEY)"))
        for table in (
            "appointments",
            "missionary_group_members",
            "missionary_groups",
            "secretary_projects",
            "secretary_task_history",
            "secretary_task_missionaries",
            "secretary_tasks",
            "stage_history",
        ):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        if schema_version >= 2:
            connection.execute(
                text(
                    "CREATE TABLE dynamics_roster_imports (id INTEGER PRIMARY KEY, "
                    "preview_id VARCHAR, status VARCHAR, filename VARCHAR, file_sha256 VARCHAR)"
                )
            )
        if include_residency:
            connection.execute(
                text(
                    "CREATE TABLE residency_events (id INTEGER PRIMARY KEY, "
                    "missionary_id INTEGER NOT NULL, event_type VARCHAR NOT NULL, "
                    "sequence_number INTEGER NOT NULL, status VARCHAR)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO residency_events VALUES "
                    "(1, 7, 'INITIAL_RESIDENCY', 0, 'APPROVED'), "
                    "(2, 7, 'INITIAL_RESIDENCY', 0, 'APPROVED')"
                )
            )
        else:
            connection.execute(
                text("CREATE TABLE residency_events (id INTEGER PRIMARY KEY)")
            )
    return engine


def test_schema_three_upgrades_to_four_and_records_ledger():
    engine = _released_schema_engine()

    assert migration_required(engine) is True
    result = run_migrations(engine)

    assert result.starting_version == 3
    assert result.ending_version == SCHEMA_VERSION
    assert result.applied == (4,)
    assert migration_required(engine) is False
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT value FROM app_metadata WHERE key = 'schema_version'")
        ).scalar_one() == "4"
        ledger = connection.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        ).scalars().all()
        rows = connection.execute(
            text("SELECT id, sequence_number, status FROM residency_events ORDER BY id")
        ).all()
    assert ledger == [1, 2, 3, 4]
    assert rows == [(1, -1, "SUPERSEDED"), (2, 0, "APPROVED")]
    assert "upload_id" in {
        column["name"] for column in inspect(engine).get_columns("documents")
    }


def test_failed_migration_does_not_advance_schema_version():
    engine = _released_schema_engine(include_residency=False)

    try:
        run_migrations(engine)
    except MigrationExecutionError as exc:
        assert isinstance(exc.__cause__, MigrationValidationError)
    else:
        raise AssertionError("missing residency table must fail migration 4")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT value FROM app_metadata WHERE key = 'schema_version'")
        ).scalar_one() == "3"
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = 4")
        ).scalar_one() == 0
    assert "upload_id" not in {
        column["name"] for column in inspect(engine).get_columns("documents")
    }


def test_applied_migration_checksum_drift_is_rejected():
    engine = _released_schema_engine()
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE schema_migrations SET checksum = 'changed' WHERE version = 2")
        )

    try:
        run_migrations(engine)
    except MigrationChecksumMismatchError as exc:
        assert "migration 2" in str(exc).lower()
    else:
        raise AssertionError("changed migration checksum must be rejected")


def test_fresh_database_is_created_and_stamped_without_replaying_upgrades():
    _load_models()
    engine = create_engine("sqlite:///:memory:")

    result = initialize_fresh_database(
        engine,
        lambda: Base.metadata.create_all(bind=engine),
    )

    assert result.starting_version == 0
    assert result.ending_version == SCHEMA_VERSION
    assert result.applied == (1, 2, 3, 4)
    assert migration_required(engine) is False


def test_every_released_schema_has_a_sequential_upgrade_path():
    for starting_version in (1, 2, 3):
        engine = _released_schema_engine(starting_version)

        result = run_migrations(engine)

        assert result.starting_version == starting_version
        assert result.applied == tuple(range(starting_version + 1, SCHEMA_VERSION + 1))
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT value FROM app_metadata WHERE key = 'schema_version'")
            ).scalar_one() == str(SCHEMA_VERSION)
