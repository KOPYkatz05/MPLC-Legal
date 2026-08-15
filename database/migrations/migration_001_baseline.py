from database.migrations.helpers import Migration, require_columns, require_tables


def upgrade(_connection):
    # Schema 1 predates the versioned runner. Existing schema-1 databases are
    # adopted only after their released core contract has been inspected.
    return None


def validate(connection):
    require_tables(
        connection,
        {
            "app_metadata",
            "appointments",
            "documents",
            "missionary_group_members",
            "missionary_groups",
            "missionaries",
            "residency_events",
            "secretary_projects",
            "secretary_task_history",
            "secretary_task_missionaries",
            "secretary_tasks",
            "stage_history",
            "workflow_stages",
        },
    )
    require_columns(connection, "missionaries", {"id", "full_name", "current_stage"})
    require_columns(
        connection,
        "documents",
        {"id", "missionary_id", "document_type", "file_path"},
    )


MIGRATION = Migration(
    version=1,
    name="released_schema_1_baseline",
    checksum="schema-1-baseline-v1",
    upgrade=upgrade,
    validate=validate,
)
