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
    from database.models.appointment import Appointment
    from database.models.secretary_work import SecretaryProject, SecretaryTask
    from database.models.residency_event import ResidencyEvent

    Base.metadata.create_all(bind=engine)

    _run_migrations()


def _run_migrations():
    migrations = [
        "ALTER TABLE documents ADD COLUMN notes TEXT",
        "ALTER TABLE documents ADD COLUMN status VARCHAR NOT NULL DEFAULT 'ACTIVE'",
        "ALTER TABLE documents ADD COLUMN invalidated_at DATETIME",
        "ALTER TABLE documents ADD COLUMN invalidated_reason VARCHAR",
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
                    "UPDATE documents "
                    "SET status = 'ACTIVE' "
                    "WHERE status IS NULL OR TRIM(status) = ''"
                )
            )
            conn.commit()
        except Exception:
            pass

        appointment_backfills = [
            (
                "interpol_appointment_date",
                "Interpol",
            ),
            (
                "biometric_appointment_date",
                "Biometric",
            ),
            (
                "pickup_appointment_date",
                "Pickup",
            ),
        ]
        for field, label in appointment_backfills:
            try:
                from sqlalchemy import text
                conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(missionary_id, appointment_field, appointment_type, scheduled_date, status) "
                        "SELECT id, :field, :label, "
                        f"{field}, 'SCHEDULED' "
                        "FROM missionaries m "
                        f"WHERE {field} IS NOT NULL "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM appointments a "
                        "WHERE a.missionary_id = m.id "
                        "AND a.appointment_field = :field "
                        f"AND a.scheduled_date = m.{field}"
                        ")"
                    ),
                    {"field": field, "label": label},
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
