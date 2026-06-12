from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///data/app.db"

engine = create_engine(
    DATABASE_URL,
    echo=False
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

Base = declarative_base()


def init_db():
    from database.models.missionary import Missionary
    from database.models.workflow import WorkflowStage
    from database.models.document import Document
    from database.models.stage_history import StageHistory
    from database.models.residency_event import ResidencyEvent

    Base.metadata.create_all(bind=engine)

    _run_migrations()


def _run_migrations():
    migrations = [
        "ALTER TABLE documents ADD COLUMN notes TEXT",
        "ALTER TABLE missionaries ADD COLUMN missionary_code TEXT",
        "ALTER TABLE missionaries ADD COLUMN deleted_at DATETIME",
        "ALTER TABLE missionaries ADD COLUMN passport_expiration DATE",
        "ALTER TABLE missionaries ADD COLUMN interpol_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN biometric_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN pickup_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN field_sources TEXT",
        "ALTER TABLE missionaries ADD COLUMN tramite_usuario TEXT",
        "ALTER TABLE missionaries ADD COLUMN tramite_contrasena TEXT",
        "ALTER TABLE documents ADD COLUMN ocr_raw_data TEXT",
        "ALTER TABLE documents ADD COLUMN ocr_confirmed_data TEXT",
        (
            "CREATE TABLE residency_events ("
            "id INTEGER NOT NULL, "
            "missionary_id INTEGER NOT NULL, "
            "event_type VARCHAR NOT NULL, "
            "sequence_number INTEGER NOT NULL, "
            "status VARCHAR, "
            "document_id INTEGER, "
            "approved_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "notes VARCHAR, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (id), "
            "FOREIGN KEY(missionary_id) REFERENCES missionaries (id), "
            "FOREIGN KEY(document_id) REFERENCES documents (id)"
            ")"
        ),
        (
            "CREATE INDEX idx_residency_events_missionary_type_sequence "
            "ON residency_events(missionary_id, event_type, sequence_number)"
        ),
    ]

    with engine.connect() as conn:
        for sql in migrations:
            try:
                from sqlalchemy import text
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass

        try:
            from sqlalchemy import text
            conn.execute(
                text(
                    "UPDATE missionaries "
                    "SET missionary_code = CAST(id AS TEXT) "
                    "WHERE missionary_code IS NULL "
                    "OR TRIM(missionary_code) = ''"
                )
            )
            conn.commit()
        except Exception:
            pass

        try:
            from sqlalchemy import text
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX "
                    "idx_missionaries_missionary_code "
                    "ON missionaries(missionary_code)"
                )
            )
            conn.commit()
        except Exception:
            pass
