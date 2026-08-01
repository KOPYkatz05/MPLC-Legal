import os
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from database.runtime import ensure_runtime_directories, get_database_path, sqlite_url
from database.base import Base


REMOTE_CLIENT = os.environ.get("MISSION_LEGAL_REMOTE_CLIENT") == "1"


def _remote_database_error():
    raise RuntimeError(
        "Direct database access is disabled in a paired Mission Legal client."
    )


if REMOTE_CLIENT:
    DATABASE_PATH = None
    DATABASE_URL = None
    engine = None
    SessionLocal = _remote_database_error
else:
    ensure_runtime_directories()
    DATABASE_PATH = get_database_path()
    DATABASE_URL = sqlite_url(DATABASE_PATH)

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
        finally:
            cursor.close()

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )


def init_db():
    if REMOTE_CLIENT:
        _remote_database_error()

    from database.models.missionary import DynamicsRosterImport, Missionary
    from database.models.workflow import WorkflowStage
    from database.models.document import Document
    from database.models.stage_history import StageHistory
    from database.models.appointment import Appointment
    from database.models.secretary_work import (
        MissionaryGroup,
        MissionaryGroupMember,
        SecretaryProject,
        SecretaryTask,
        SecretaryTaskHistory,
        SecretaryTaskMissionary,
    )
    from database.models.residency_event import ResidencyEvent

    Base.metadata.create_all(bind=engine)

    _run_migrations()

    from database.schema import record_schema_version

    record_schema_version(engine)


def _run_migrations():
    migrations = [
        "ALTER TABLE documents ADD COLUMN notes TEXT",
        "ALTER TABLE documents ADD COLUMN status VARCHAR NOT NULL DEFAULT 'ACTIVE'",
        "ALTER TABLE documents ADD COLUMN invalidated_at DATETIME",
        "ALTER TABLE documents ADD COLUMN invalidated_reason VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN missionary_code TEXT",
        "ALTER TABLE missionaries ADD COLUMN row_color VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN deleted_at DATETIME",
        "ALTER TABLE missionaries ADD COLUMN date_of_birth DATE",
        "ALTER TABLE missionaries ADD COLUMN passport_expiration DATE",
        "ALTER TABLE missionaries ADD COLUMN interpol_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN biometric_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN pickup_appointment_date DATE",
        "ALTER TABLE missionaries ADD COLUMN field_sources TEXT",
        "ALTER TABLE missionaries ADD COLUMN tramite_usuario TEXT",
        "ALTER TABLE missionaries ADD COLUMN tramite_contrasena TEXT",
        "ALTER TABLE missionaries ADD COLUMN carnet_number TEXT",
        "ALTER TABLE missionaries ADD COLUMN dni_number TEXT",
        "ALTER TABLE missionaries ADD COLUMN tracking_profile VARCHAR DEFAULT 'LEGAL'",
        "ALTER TABLE missionaries ADD COLUMN dynamics_contact_id VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN dynamics_row_checksum VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN dynamics_modified_at DATETIME",
        "ALTER TABLE missionaries ADD COLUMN dynamics_status VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN release_date DATE",
        "ALTER TABLE missionaries ADD COLUMN home_address TEXT",
        "ALTER TABLE missionaries ADD COLUMN father_name VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN mother_name VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN father_first_name_override VARCHAR",
        "ALTER TABLE missionaries ADD COLUMN mother_first_name_override VARCHAR",
        """
        CREATE TABLE dynamics_roster_imports (
            id INTEGER PRIMARY KEY,
            preview_id VARCHAR NOT NULL UNIQUE,
            status VARCHAR NOT NULL DEFAULT 'PREVIEW',
            filename VARCHAR NOT NULL,
            filename_timestamp VARCHAR,
            file_sha256 VARCHAR NOT NULL,
            dynamics_modified_at DATETIME,
            summary_json TEXT,
            applying_device VARCHAR,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        )
        """,
        "ALTER TABLE documents ADD COLUMN ocr_raw_data TEXT",
        "ALTER TABLE documents ADD COLUMN ocr_confirmed_data TEXT",
        "ALTER TABLE appointments ADD COLUMN appointment_uid VARCHAR",
        "ALTER TABLE appointments ADD COLUMN closed_at DATETIME",
        "ALTER TABLE appointments ADD COLUMN status_reason VARCHAR",
        "ALTER TABLE appointments ADD COLUMN superseded_by_uid VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN waiting_reason VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN group_id INTEGER",
        "ALTER TABLE secretary_tasks ADD COLUMN group_scope_label VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN work_date DATE",
        "ALTER TABLE secretary_tasks ADD COLUMN board_lane VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN board_position INTEGER",
        "ALTER TABLE secretary_tasks ADD COLUMN task_type VARCHAR NOT NULL DEFAULT 'CUSTOM'",
        "ALTER TABLE secretary_tasks ADD COLUMN related_stage VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN related_document_type VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN automation_key VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN automation_source VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN automation_status_reason VARCHAR",
        "ALTER TABLE secretary_tasks ADD COLUMN waiting_follow_up_date DATE",
        "ALTER TABLE missionary_groups ADD COLUMN group_type VARCHAR",
        "ALTER TABLE missionary_groups ADD COLUMN automation_key VARCHAR",
        """
        CREATE TABLE missionary_groups (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            description VARCHAR,
            group_type VARCHAR,
            automation_key VARCHAR,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE missionary_group_members (
            group_id INTEGER NOT NULL,
            missionary_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, missionary_id),
            FOREIGN KEY(group_id) REFERENCES missionary_groups(id),
            FOREIGN KEY(missionary_id) REFERENCES missionaries(id)
        )
        """,
        """
        CREATE TABLE secretary_task_missionaries (
            task_id INTEGER NOT NULL,
            missionary_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_id, missionary_id),
            FOREIGN KEY(task_id) REFERENCES secretary_tasks(id),
            FOREIGN KEY(missionary_id) REFERENCES missionaries(id)
        )
        """,
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
            work_date DATE,
            project_id INTEGER,
            missionary_id INTEGER,
            group_id INTEGER,
            group_scope_label VARCHAR,
            appointment_field VARCHAR,
            task_type VARCHAR NOT NULL DEFAULT 'CUSTOM',
            related_stage VARCHAR,
            related_document_type VARCHAR,
            automation_key VARCHAR,
            automation_source VARCHAR,
            automation_status_reason VARCHAR,
            waiting_reason VARCHAR,
            waiting_follow_up_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY(project_id) REFERENCES secretary_projects(id),
            FOREIGN KEY(missionary_id) REFERENCES missionaries(id),
            FOREIGN KEY(group_id) REFERENCES missionary_groups(id)
        )
        """,
        """
        CREATE TABLE secretary_task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            event_type VARCHAR NOT NULL,
            old_value VARCHAR,
            new_value VARCHAR,
            note VARCHAR,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES secretary_tasks(id)
        )
        """,
        "CREATE INDEX idx_secretary_projects_status ON secretary_projects(status)",
        "CREATE INDEX idx_secretary_projects_due_date ON secretary_projects(due_date)",
        "CREATE INDEX idx_secretary_tasks_status ON secretary_tasks(status)",
        "CREATE INDEX idx_secretary_tasks_due_date ON secretary_tasks(due_date)",
        "CREATE INDEX idx_secretary_tasks_project_id ON secretary_tasks(project_id)",
        "CREATE INDEX idx_secretary_tasks_missionary_id ON secretary_tasks(missionary_id)",
        "CREATE INDEX idx_secretary_tasks_group_id ON secretary_tasks(group_id)",
        "CREATE INDEX idx_secretary_tasks_board_lane ON secretary_tasks(board_lane)",
        "CREATE INDEX idx_secretary_tasks_board_lane_position ON secretary_tasks(board_lane, board_position)",
        "CREATE UNIQUE INDEX idx_secretary_tasks_automation_key ON secretary_tasks(automation_key)",
        "CREATE INDEX idx_secretary_task_history_task_id ON secretary_task_history(task_id)",
        "CREATE INDEX idx_missionary_group_members_missionary_id ON missionary_group_members(missionary_id)",
        "CREATE INDEX idx_secretary_task_missionaries_missionary_id ON secretary_task_missionaries(missionary_id)",
        """
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY,
            appointment_uid VARCHAR NOT NULL,
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
        "CREATE UNIQUE INDEX idx_appointments_uid ON appointments(appointment_uid)",
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
            except OperationalError as exc:
                message = str(getattr(exc, "orig", exc)).lower()
                if (
                    "duplicate column name" in message
                    or "already exists" in message
                    # Targeted migration tests and recovery tools may operate on
                    # a partial legacy schema. init_db() creates the complete
                    # model schema before this runner executes in production.
                    or "no such table" in message
                    or "no such column" in message
                ):
                    conn.rollback()
                    continue
                conn.rollback()
                raise RuntimeError(
                    f"Database migration failed: {sql.strip()[:100]}"
                ) from exc

        try:
            from sqlalchemy import text
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO secretary_task_missionaries "
                    "(task_id, missionary_id) "
                    "SELECT id, missionary_id FROM secretary_tasks "
                    "WHERE missionary_id IS NOT NULL"
                )
            )
            conn.commit()
        except Exception:
            pass

        try:
            from sqlalchemy import text
            conn.execute(
                text(
                    "UPDATE secretary_tasks "
                    "SET work_date = due_date "
                    "WHERE work_date IS NULL AND due_date IS NOT NULL"
                )
            )
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

        try:
            from sqlalchemy import text
            rows = conn.execute(
                text(
                    "SELECT id FROM appointments "
                    "WHERE appointment_uid IS NULL "
                    "OR TRIM(appointment_uid) = ''"
                )
            ).fetchall()
            for row in rows:
                conn.execute(
                    text(
                        "UPDATE appointments "
                        "SET appointment_uid = :appointment_uid "
                        "WHERE id = :id"
                    ),
                    {
                        "appointment_uid": uuid.uuid4().hex,
                        "id": row[0],
                    },
                )
            conn.commit()
        except Exception:
            pass

        try:
            from sqlalchemy import text
            duplicate_groups = conn.execute(
                text(
                    "SELECT missionary_id, appointment_field, scheduled_date, "
                    "MIN(id) AS keep_id "
                    "FROM appointments "
                    "WHERE status = 'SCHEDULED' "
                    "GROUP BY missionary_id, appointment_field, scheduled_date "
                    "HAVING COUNT(*) > 1"
                )
            ).fetchall()
            for row in duplicate_groups:
                conn.execute(
                    text(
                        "UPDATE appointments "
                        "SET status = 'MISSED', "
                        "marked_at = COALESCE(marked_at, CURRENT_TIMESTAMP), "
                        "closed_at = COALESCE(closed_at, CURRENT_TIMESTAMP), "
                        "status_reason = "
                        "'Duplicate scheduled cita reconciled during migration' "
                        "WHERE status = 'SCHEDULED' "
                        "AND missionary_id = :missionary_id "
                        "AND appointment_field = :appointment_field "
                        "AND scheduled_date = :scheduled_date "
                        "AND id != :keep_id"
                    ),
                    {
                        "missionary_id": row[0],
                        "appointment_field": row[1],
                        "scheduled_date": row[2],
                        "keep_id": row[3],
                    },
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
                        "(appointment_uid, missionary_id, appointment_field, "
                        "appointment_type, scheduled_date, status) "
                        "SELECT lower(hex(randomblob(16))), id, :field, :label, "
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

        try:
            from sqlalchemy import text
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX "
                    "idx_appointments_scheduled_unique "
                    "ON appointments("
                    "missionary_id, appointment_field, scheduled_date"
                    ") "
                    "WHERE status = 'SCHEDULED'"
                )
            )
            conn.commit()
        except Exception:
            pass
