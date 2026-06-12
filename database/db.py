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
        """
        CREATE TABLE secretary_projects (
            id INTEGER PRIMARY KEY,
            title VARCHAR NOT NULL,
            description VARCHAR,
            status VARCHAR NOT NULL DEFAULT 'ACTIVE',
            priority VARCHAR NOT NULL DEFAULT 'NORMAL',
            due_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        )
        """,
        """
        CREATE TABLE secretary_tasks (
            id INTEGER PRIMARY KEY,
            title VARCHAR NOT NULL,
            description VARCHAR,
            status VARCHAR NOT NULL DEFAULT 'OPEN',
            priority VARCHAR NOT NULL DEFAULT 'NORMAL',
            due_date DATE,
            project_id INTEGER,
            missionary_id INTEGER,
            appointment_field VARCHAR,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY(project_id) REFERENCES secretary_projects(id),
            FOREIGN KEY(missionary_id) REFERENCES missionaries(id)
        )
        """,
        "CREATE INDEX idx_secretary_projects_status ON secretary_projects(status)",
        "CREATE INDEX idx_secretary_projects_due_date ON secretary_projects(due_date)",
        "CREATE INDEX idx_secretary_tasks_status ON secretary_tasks(status)",
        "CREATE INDEX idx_secretary_tasks_due_date ON secretary_tasks(due_date)",
        "CREATE INDEX idx_secretary_tasks_project_id ON secretary_tasks(project_id)",
        "CREATE INDEX idx_secretary_tasks_missionary_id ON secretary_tasks(missionary_id)",
        """
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY,
            missionary_id INTEGER NOT NULL,
            appointment_field VARCHAR NOT NULL,
            appointment_type VARCHAR NOT NULL,
            scheduled_date DATE NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'SCHEDULED',
            marked_at DATETIME,
            notes VARCHAR,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(missionary_id) REFERENCES missionaries(id)
        )
        """,
        "CREATE INDEX idx_appointments_missionary_id ON appointments(missionary_id)",
        "CREATE INDEX idx_appointments_status ON appointments(status)",
        "CREATE INDEX idx_appointments_scheduled_date ON appointments(scheduled_date)",
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
