from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from database.models.secretary_work import (
    MissionaryGroupMember,
    SecretaryProject,
    SecretaryTask,
    SecretaryTaskMissionary,
)
from services import missionary_group_service as group_service_module
from services import secretary_work_service as service_module
from services.missionary_group_service import MissionaryGroupService
from services.secretary_work_service import (
    SecretaryWorkError,
    SecretaryWorkService,
    task_due_group,
)


@pytest.fixture()
def secretary_service(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(service_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(group_service_module, "SessionLocal", TestingSession)
    return SecretaryWorkService()


def _create_missionary(name):
    session = service_module.SessionLocal()
    missionary = Missionary(
        missionary_code=name.replace(" ", "-").lower(),
        full_name=name,
        status="ACTIVE",
    )
    session.add(missionary)
    session.commit()
    session.refresh(missionary)
    missionary_id = missionary.id
    session.close()
    return missionary_id


def test_create_update_complete_and_archive_task(secretary_service):
    task = secretary_service.create_task("Call office", priority="IMPORTANT")

    assert task["title"] == "Call office"
    assert task["status"] == "OPEN"
    assert task["priority"] == "IMPORTANT"

    updated = secretary_service.update_task(
        task["id"],
        title="Call mission office",
        status="WAITING",
        waiting_reason="MISSIONARY",
    )
    assert updated["title"] == "Call mission office"
    assert updated["status"] == "WAITING"

    done = secretary_service.complete_task(task["id"])
    assert done["status"] == "DONE"
    assert done["completed_at"] is not None

    archived = secretary_service.archive_task(task["id"])
    assert archived["status"] == "ARCHIVED"


def test_waiting_task_requires_reason_and_clears_when_reopened(secretary_service):
    with pytest.raises(SecretaryWorkError):
        secretary_service.create_task("Waiting task", status="WAITING")

    task = secretary_service.create_task(
        "Waiting task",
        status="WAITING",
        waiting_reason="DOCUMENT",
    )

    assert task["status"] == "WAITING"
    assert task["waiting_reason"] == "DOCUMENT"
    assert task["waiting_reason_label"] == "Waiting on document"

    reopened = secretary_service.update_task(task["id"], status="OPEN")

    assert reopened["status"] == "OPEN"
    assert reopened["waiting_reason"] is None
    assert reopened["waiting_reason_label"] == ""


def test_create_update_complete_and_archive_project(secretary_service):
    project = secretary_service.create_project(
        "June arrivals",
        priority="CRITICAL",
    )

    assert project["title"] == "June arrivals"
    assert project["status"] == "ACTIVE"

    updated = secretary_service.update_project(
        project["id"],
        status="WAITING",
        description="Waiting on passports",
    )
    assert updated["status"] == "WAITING"
    assert updated["description"] == "Waiting on passports"

    done = secretary_service.complete_project(project["id"])
    assert done["status"] == "DONE"

    archived = secretary_service.archive_project(project["id"])
    assert archived["status"] == "ARCHIVED"


def test_list_tasks_hides_done_and_archived_by_default(secretary_service):
    visible = secretary_service.create_task("Visible")
    done = secretary_service.create_task("Done")
    archived = secretary_service.create_task("Archived")
    secretary_service.complete_task(done["id"])
    secretary_service.archive_task(archived["id"])

    assert [task["title"] for task in secretary_service.list_tasks()] == [
        visible["title"]
    ]
    assert {
        task["title"]
        for task in secretary_service.list_tasks(include_done=True)
    } == {"Visible", "Done", "Archived"}


def test_delete_task_permanently_removes_record(secretary_service):
    task = secretary_service.create_task("Delete me")

    assert secretary_service.delete_task(task["id"]) is True
    assert secretary_service.list_tasks(include_done=True) == []


def test_create_task_with_multiple_missionaries_creates_one_shared_task(secretary_service):
    first_id = _create_missionary("Alpha Missionary")
    second_id = _create_missionary("Beta Missionary")

    task = secretary_service.create_task(
        "Shared pickup prep",
        missionary_ids=[first_id, second_id],
    )

    assert task["missionary_ids"] == [first_id, second_id]
    assert task["missionary_count"] == 2
    assert task["scope_label"] == "2 missionaries"
    assert task["is_group_task"] is True
    assert [item["id"] for item in secretary_service.list_tasks()] == [task["id"]]
    assert [
        item["id"]
        for item in secretary_service.list_tasks(missionary_id=first_id)
    ] == [task["id"]]
    assert [
        item["id"]
        for item in secretary_service.list_tasks(missionary_id=second_id)
    ] == [task["id"]]

    session = service_module.SessionLocal()
    links = session.query(SecretaryTaskMissionary).filter_by(task_id=task["id"]).all()
    session.close()

    assert {link.missionary_id for link in links} == {first_id, second_id}


def test_group_creation_and_group_task_snapshot(secretary_service):
    first_id = _create_missionary("June Arrival One")
    second_id = _create_missionary("June Arrival Two")
    late_id = _create_missionary("Late Addition")

    group_service = MissionaryGroupService()
    group = group_service.create_group(
        "Llegadas June 3rd",
        missionary_ids=[first_id, second_id],
    )

    assert group["member_count"] == 2

    task = secretary_service.create_task(
        "Prepare shared cita packet",
        group_id=group["id"],
    )

    group_service.update_group(
        group["id"],
        missionary_ids=[first_id, second_id, late_id],
    )

    refreshed = secretary_service.list_tasks(include_done=True)[0]

    assert refreshed["id"] == task["id"]
    assert refreshed["missionary_ids"] == [first_id, second_id]
    assert refreshed["group_scope_label"] == "Llegadas June 3rd"
    assert refreshed["scope_label"] == "2 missionaries - Llegadas June 3rd"
    assert secretary_service.list_tasks(missionary_id=late_id) == []

    edited = secretary_service.update_task(
        task["id"],
        title="Updated shared cita packet",
        missionary_ids=refreshed["missionary_ids"],
        group_id=group["id"],
    )

    assert edited["missionary_ids"] == [first_id, second_id]
    assert secretary_service.list_tasks(missionary_id=late_id) == []


def test_complete_archive_delete_shared_task_affects_single_record(secretary_service):
    first_id = _create_missionary("Shared One")
    second_id = _create_missionary("Shared Two")
    task = secretary_service.create_task(
        "Shared legal follow-up",
        missionary_ids=[first_id, second_id],
    )

    done = secretary_service.complete_task(task["id"])
    assert done["status"] == "DONE"
    assert secretary_service.list_tasks(missionary_id=first_id) == []
    assert [
        item["id"]
        for item in secretary_service.list_tasks(
            missionary_id=second_id,
            include_done=True,
        )
    ] == [task["id"]]

    archived = secretary_service.archive_task(task["id"])
    assert archived["status"] == "ARCHIVED"

    assert secretary_service.delete_task(task["id"]) is True
    assert secretary_service.list_tasks(include_done=True) == []
    session = service_module.SessionLocal()
    links = session.query(SecretaryTaskMissionary).filter_by(task_id=task["id"]).all()
    session.close()
    assert links == []


def test_grouped_tasks_by_due_date(secretary_service, monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 10)

    monkeypatch.setattr(service_module, "date", FakeDate)
    today = FakeDate.today()
    secretary_service.create_task("Past", due_date=today - timedelta(days=1))
    secretary_service.create_task("Today", due_date=today)
    secretary_service.create_task("This week", due_date=today + timedelta(days=1))
    secretary_service.create_task("Later", due_date=today + timedelta(days=10))
    secretary_service.create_task("No due")

    grouped = secretary_service.grouped_tasks()

    assert [task["title"] for task in grouped["overdue"]] == ["Past"]
    assert [task["title"] for task in grouped["today"]] == ["Today"]
    assert [task["title"] for task in grouped["this_week"]] == ["This week"]
    assert [task["title"] for task in grouped["later"]] == ["Later"]
    assert [task["title"] for task in grouped["no_due_date"]] == ["No due"]


def test_filters_by_search_status_priority_project_and_missionary(secretary_service):
    session = service_module.SessionLocal()
    missionary = Missionary(
        missionary_code="90001",
        full_name="Filtered Missionary",
        status="ACTIVE",
    )
    session.add(missionary)
    session.commit()
    session.refresh(missionary)
    session.close()

    project = secretary_service.create_project("Interpol batch")
    target = secretary_service.create_task(
        "Prepare Interpol packet",
        priority="CRITICAL",
        project_id=project["id"],
        missionary_id=missionary.id,
    )
    secretary_service.create_task("Other task", priority="LOW")

    results = secretary_service.list_tasks(
        search="packet",
        priority="CRITICAL",
        project_id=project["id"],
        missionary_id=missionary.id,
    )

    assert [task["id"] for task in results] == [target["id"]]


def test_search_matches_appointment_label(secretary_service):
    target = secretary_service.create_task(
        "Prepare packet",
        appointment_field="interpol_appointment_date",
    )
    secretary_service.create_task("Other task")

    results = secretary_service.list_tasks(search="interpol")

    assert [task["id"] for task in results] == [target["id"]]


def test_secretary_task_waiting_reason_migration(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE missionaries (
                    id INTEGER PRIMARY KEY,
                    full_name VARCHAR,
                    status VARCHAR
                )
                """
            )
        )
        conn.execute(
            text(
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
                    completed_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO missionaries (id, full_name, status) "
                "VALUES (5, 'Existing Missionary', 'ACTIVE')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO secretary_tasks "
                "(id, title, status, priority, missionary_id) "
                "VALUES (10, 'Existing Task', 'OPEN', 'NORMAL', 5)"
            )
        )

    from database import db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    db_module._run_migrations()

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(secretary_tasks)"))
        }
        group_tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table'"
                )
            )
        }
        backfilled_links = conn.execute(
            text(
                "SELECT task_id, missionary_id "
                "FROM secretary_task_missionaries"
            )
        ).fetchall()

    assert "waiting_reason" in columns
    assert "group_id" in columns
    assert "group_scope_label" in columns
    assert "missionary_groups" in group_tables
    assert "missionary_group_members" in group_tables
    assert "secretary_task_missionaries" in group_tables
    assert backfilled_links == [(10, 5)]


def test_project_progress_counts_tasks(secretary_service):
    project = secretary_service.create_project("Pickup week")
    open_task = secretary_service.create_task("Open", project_id=project["id"])
    done_task = secretary_service.create_task("Done", project_id=project["id"])
    archived_task = secretary_service.create_task("Archived", project_id=project["id"])
    secretary_service.complete_task(done_task["id"])
    secretary_service.archive_task(archived_task["id"])

    refreshed = secretary_service.list_projects(include_done=True)[0]

    assert refreshed["open_tasks"] == 1
    assert refreshed["done_tasks"] == 1
    assert refreshed["total_tasks"] == 2
    assert refreshed["progress"] == "1/2 done"


def test_title_is_required(secretary_service):
    with pytest.raises(SecretaryWorkError):
        secretary_service.create_task("")

    with pytest.raises(SecretaryWorkError):
        secretary_service.create_project("")


def test_task_due_group():
    today = date(2026, 6, 10)

    assert task_due_group(None, today) == "no_due_date"
    assert task_due_group(today - timedelta(days=1), today) == "overdue"
    assert task_due_group(today, today) == "today"
    assert task_due_group(today + timedelta(days=2), today) == "this_week"
    assert task_due_group(today + timedelta(days=10), today) == "later"
