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
    from database.models.secretary_work import SecretaryProject, SecretaryTask

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
