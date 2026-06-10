from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryProject, SecretaryTask
from services import secretary_work_service as service_module
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
    return SecretaryWorkService()


def test_create_update_complete_and_archive_task(secretary_service):
    task = secretary_service.create_task("Call office", priority="IMPORTANT")

    assert task["title"] == "Call office"
    assert task["status"] == "OPEN"
    assert task["priority"] == "IMPORTANT"

    updated = secretary_service.update_task(
        task["id"],
        title="Call mission office",
        status="WAITING",
    )
    assert updated["title"] == "Call mission office"
    assert updated["status"] == "WAITING"

    done = secretary_service.complete_task(task["id"])
    assert done["status"] == "DONE"
    assert done["completed_at"] is not None

    archived = secretary_service.archive_task(task["id"])
    assert archived["status"] == "ARCHIVED"


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


def test_grouped_tasks_by_due_date(secretary_service):
    today = date.today()
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
