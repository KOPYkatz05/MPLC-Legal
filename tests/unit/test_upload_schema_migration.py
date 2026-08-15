from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database import db as db_module


def test_upload_migration_adds_idempotency_columns_and_preserves_duplicate_events(
    monkeypatch,
):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE documents ("
                "id INTEGER PRIMARY KEY, missionary_id INTEGER, "
                "document_type VARCHAR, workflow_stage VARCHAR, "
                "file_name VARCHAR, file_path VARCHAR)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE residency_events ("
                "id INTEGER PRIMARY KEY, missionary_id INTEGER NOT NULL, "
                "event_type VARCHAR NOT NULL, sequence_number INTEGER NOT NULL, "
                "status VARCHAR, document_id INTEGER, notes VARCHAR)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO residency_events "
                "(id, missionary_id, event_type, sequence_number, status) "
                "VALUES (1, 7, 'INITIAL_RESIDENCY', 0, 'APPROVED'), "
                "(2, 7, 'INITIAL_RESIDENCY', 0, 'APPROVED')"
            )
        )

    monkeypatch.setattr(db_module, "engine", engine)
    db_module._run_migrations()

    document_columns = {
        column["name"] for column in inspect(engine).get_columns("documents")
    }
    assert {
        "upload_id",
        "content_sha256",
        "file_size",
        "supersedes_document_id",
        "post_processing_status",
        "post_processing_error",
        "post_processing_updated_fields",
    }.issubset(document_columns)
    assert any(
        index["name"] == "uq_documents_upload_id" and index["unique"]
        for index in inspect(engine).get_indexes("documents")
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, sequence_number, status FROM residency_events "
                "ORDER BY id"
            )
        ).all()
    assert rows == [
        (1, -1, "SUPERSEDED"),
        (2, 0, "APPROVED"),
    ]

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO residency_events "
                "(id, missionary_id, event_type, sequence_number, status) "
                "VALUES (3, 7, 'PRORROGA', 1, 'APPROVED')"
            )
        )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO residency_events "
                    "(id, missionary_id, event_type, sequence_number, status) "
                    "VALUES (4, 7, 'PRORROGA', 1, 'APPROVED')"
                )
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("residency event identity must be unique")
