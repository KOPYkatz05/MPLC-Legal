from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import (
    MissionaryGroup,
    MissionaryGroupMember,
    SecretaryProject,
    SecretaryTask,
    SecretaryTaskHistory,
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
    task = secretary_service.create_task(
        "Call office",
        priority="IMPORTANT",
        work_date=date(2026, 6, 8),
        due_date=date(2026, 6, 12),
    )

    assert task["title"] == "Call office"
    assert task["status"] == "OPEN"
    assert task["priority"] == "IMPORTANT"
    assert task["work_date"] == date(2026, 6, 8)
    assert task["due_date"] == date(2026, 6, 12)

    updated = secretary_service.update_task(
        task["id"],
        title="Call mission office",
        status="WAITING",
        waiting_reason="MISSIONARY",
        work_date=date(2026, 6, 9),
    )
    assert updated["title"] == "Call mission office"
    assert updated["status"] == "WAITING"
    assert updated["work_date"] == date(2026, 6, 9)

    done = secretary_service.complete_task(task["id"])
    assert done["status"] == "DONE"
    assert done["completed_at"] is not None

    archived = secretary_service.archive_task(task["id"])
    assert archived["status"] == "ARCHIVED"


def test_task_status_history_tracks_creation_and_transitions(secretary_service):
    task = secretary_service.create_task("Track status")

    secretary_service.mark_task_ready(task["id"])
    secretary_service.update_task(
        task["id"],
        status="WAITING",
        waiting_reason="DOCUMENT",
    )
    secretary_service.complete_task(task["id"])

    session = service_module.SessionLocal()
    try:
        rows = (
            session.query(SecretaryTaskHistory)
            .filter_by(task_id=task["id"])
            .order_by(SecretaryTaskHistory.id)
            .all()
        )
        values = [
            (row.old_value, row.new_value, row.note or "")
            for row in rows
        ]
    finally:
        session.close()

    assert values == [
        (None, "OPEN", "Task created"),
        ("OPEN", "READY", ""),
        ("READY", "WAITING", ""),
        ("WAITING", "DONE", ""),
    ]

    history = secretary_service.get_task_status_history(task["id"])

    assert history[0]["summary"] == "Waiting -> Done"
    assert history[-1]["summary"] == "Created as To Do"


def test_obsolete_automatic_archive_records_status_history(secretary_service):
    task = secretary_service.create_task(
        "Generated task",
        automation_key="auto:stale",
        automation_source="process_automation",
    )

    archived = secretary_service.archive_obsolete_automatic_tasks(
        active_keys=[],
        source="process_automation",
        prefixes=["auto:"],
        reason="No longer current",
    )
    history = secretary_service.get_task_status_history(task["id"])

    assert archived == 1
    assert history[0]["summary"] == "To Do -> Archived"
    assert history[0]["note"] == "No longer current"


def test_ready_status_is_visible_grouped_and_counted(secretary_service, monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 10)

    monkeypatch.setattr(service_module, "date", FakeDate)

    ready = secretary_service.create_task(
        "Review complete packet",
        status="READY",
        due_date=FakeDate.today() - timedelta(days=1),
    )
    secretary_service.create_task("Normal task")

    visible = secretary_service.list_tasks()
    grouped = secretary_service.grouped_tasks()
    summary = secretary_service.summary()

    assert ready["status"] == "READY"
    assert {task["status"] for task in visible} == {"OPEN", "READY"}
    assert [task["title"] for task in grouped["ready_to_review"]] == [
        "Review complete packet"
    ]
    assert grouped["overdue"] == []
    assert summary["ready"] == 1
    assert summary["open"] == 1
    assert summary["overdue"] == 1


def test_task_classification_fields_round_trip_and_filter(secretary_service):
    target = secretary_service.create_task(
        "Upload Prorroga approval",
        status="READY",
        task_type="DOCUMENT",
        related_stage="PRORROGA",
        related_document_type="APROBACION_DE_PRORROGA",
    )
    secretary_service.create_task("General follow-up")

    by_type = secretary_service.list_tasks(task_type="DOCUMENT")
    by_search = secretary_service.list_tasks(search="prorroga approval")

    assert target["task_type"] == "DOCUMENT"
    assert target["task_type_label"] == "Document"
    assert target["related_stage"] == "PRORROGA"
    assert target["related_document_type"] == "APROBACION_DE_PRORROGA"
    assert target["related_document_label"]
    assert [task["id"] for task in by_type] == [target["id"]]
    assert [task["id"] for task in by_search] == [target["id"]]


def test_appointment_filter_includes_legacy_appointment_tasks(secretary_service):
    target = secretary_service.create_task(
        "Prepare appointment packet",
        appointment_field="interpol_appointment_date",
    )
    secretary_service.create_task("Document task", task_type="DOCUMENT")

    results = secretary_service.list_tasks(task_type="APPOINTMENT")

    assert [task["id"] for task in results] == [target["id"]]


def test_filters_by_related_stage(secretary_service):
    target = secretary_service.create_task(
        "Review Interpol packet",
        related_stage="INTERPOL",
    )
    secretary_service.create_task(
        "Review Prorroga packet",
        related_stage="PRORROGA",
    )
    secretary_service.create_task("General office task")

    results = secretary_service.list_tasks(related_stage="INTERPOL")

    assert [task["id"] for task in results] == [target["id"]]


def test_filters_by_related_document_type(secretary_service):
    target = secretary_service.create_task(
        "Review passport",
        related_document_type="PASSPORT",
    )
    secretary_service.create_task(
        "Review FBI",
        related_document_type="FBI",
    )
    secretary_service.create_task("General office task")

    results = secretary_service.list_tasks(related_document_type="PASSPORT")

    assert [task["id"] for task in results] == [target["id"]]


def test_filters_by_automation_state(secretary_service):
    manual = secretary_service.create_task("Manual follow-up")
    automated = secretary_service.create_task(
        "Generated passport reminder",
        automation_key="auto:passport",
        automation_source="process_automation",
    )

    auto_results = secretary_service.list_tasks(automation_state="AUTO")
    manual_results = secretary_service.list_tasks(automation_state="MANUAL")

    assert [task["id"] for task in auto_results] == [automated["id"]]
    assert [task["id"] for task in manual_results] == [manual["id"]]


def test_automatic_task_preserves_completed_task(secretary_service):
    created = secretary_service.create_or_update_automatic_task(
        automation_key="auto:ready-preserve",
        automation_source="test",
        title="Original title",
        task_type="DOCUMENT",
        related_stage="INTERPOL",
    )
    secretary_service.complete_task(created["id"])

    skipped = secretary_service.create_or_update_automatic_task(
        automation_key="auto:ready-preserve",
        automation_source="test",
        title="Changed title",
        task_type="APPOINTMENT",
        related_stage="PRORROGA",
    )

    assert skipped["automation_result"] == "skipped"
    assert skipped["title"] == "Original title"
    assert skipped["status"] == "DONE"
    assert skipped["task_type"] == "DOCUMENT"
    assert skipped["related_stage"] == "INTERPOL"


def test_automatic_task_update_keeps_classification_when_omitted(secretary_service):
    created = secretary_service.create_or_update_automatic_task(
        automation_key="auto:classification-preserve",
        automation_source="test",
        title="Original title",
        task_type="DOCUMENT",
        related_stage="INTERPOL",
        related_document_type="PASSPORT",
    )

    updated = secretary_service.create_or_update_automatic_task(
        automation_key="auto:classification-preserve",
        automation_source="test",
        title="Updated title",
    )

    assert updated["automation_result"] == "updated"
    assert updated["title"] == "Updated title"
    assert created["task_type"] == "DOCUMENT"
    assert updated["task_type"] == "DOCUMENT"
    assert updated["related_stage"] == "INTERPOL"
    assert updated["related_document_type"] == "PASSPORT"


def test_task_workspace_includes_grouped_prorroga_context(secretary_service):
    session = service_module.SessionLocal()
    try:
        first = Missionary(
            missionary_code="elder-one",
            full_name="Elder One",
            status="ACTIVE",
            current_stage="PRORROGA",
            residency_expiration=date(2026, 8, 9),
        )
        second = Missionary(
            missionary_code="sister-two",
            full_name="Sister Two",
            status="ACTIVE",
            current_stage="PRORROGA",
            residency_expiration=date(2026, 8, 11),
        )
        group = MissionaryGroup(
            name="Temporary - Critical Prorroga follow-up needed",
            group_type="TEMPORARY_AUTOMATION",
            automation_key="prorroga:group:30:2026-07-10",
        )
        session.add_all([first, second, group])
        session.flush()
        task = SecretaryTask(
            title="Critical Prorroga follow-up needed",
            description="2 missionaries need this prorroga step.",
            status="OPEN",
            priority="CRITICAL",
            due_date=date(2026, 7, 10),
            group_id=group.id,
            group_scope_label=group.name,
            automation_key="prorroga:group:30:2026-07-10",
            automation_source="process_automation",
        )
        session.add(task)
        session.flush()
        session.add_all([
            SecretaryTaskMissionary(task_id=task.id, missionary_id=first.id),
            SecretaryTaskMissionary(task_id=task.id, missionary_id=second.id),
            MissionaryGroupMember(group_id=group.id, missionary_id=first.id),
            MissionaryGroupMember(group_id=group.id, missionary_id=second.id),
        ])
        session.commit()
        task_id = task.id
    finally:
        session.close()

    workspace = secretary_service.get_task_workspace(
        task_id,
        today=date(2026, 7, 29),
    )

    assert workspace["timing"] == "19 day(s) overdue"
    assert "Prorroga follow-up is 19 day(s) overdue" in workspace["brief_text"]
    assert "Prorroga follow-up" in workspace["why_text"]
    assert "Created by process automation" in workspace["why_points"]
    assert workspace["key_facts"][0]["label"] == "Due"
    assert len(workspace["affected_missionaries"]) == 2
    assert workspace["affected_missionaries"][0]["issue_flags"]
    assert any(
        item["label"] == "Automation key"
        for item in workspace["evidence"]
    )
    assert workspace["recommended_steps"][0] == (
        "Review each affected missionary record."
    )


def test_task_workspace_uses_manual_task_fallback(secretary_service):
    task = secretary_service.create_task(
        "Call mission office",
        description="Ask for missing travel confirmation.",
        due_date=date(2026, 6, 12),
    )
    secretary_service.mark_task_ready(task["id"])

    workspace = secretary_service.get_task_workspace(
        task["id"],
        today=date(2026, 6, 13),
    )

    assert "Ask for missing travel confirmation." in workspace["why_text"]
    assert workspace["affected_missionaries"] == []
    assert workspace["status_history"][0]["summary"] == "To Do -> Ready"
    assert any(
        item["label"] == "Last status change"
        and item["value"] == "To Do -> Ready"
        for item in workspace["evidence"]
    )
    assert workspace["recommended_steps"][-1] == (
        "Mark this task done when the work is resolved."
    )


def test_ready_workspace_uses_related_document_and_stage(secretary_service):
    session = service_module.SessionLocal()
    try:
        first = Missionary(
            missionary_code="ready-one",
            full_name="Ready One",
            status="ACTIVE",
            current_stage="PRORROGA",
        )
        second = Missionary(
            missionary_code="ready-two",
            full_name="Ready Two",
            status="ACTIVE",
            current_stage="INTERPOL",
        )
        session.add_all([first, second])
        session.flush()
        session.add(
            Document(
                missionary_id=first.id,
                document_type="APROBACION_DE_PRORROGA",
                workflow_stage="PRORROGA",
                verified=True,
                file_name="approval.pdf",
                file_path="approval.pdf",
                status="ACTIVE",
            )
        )
        session.commit()
        first_id = first.id
        second_id = second.id
    finally:
        session.close()

    task = secretary_service.create_task(
        "Review Prorroga approval",
        status="READY",
        task_type="DOCUMENT",
        related_stage="PRORROGA",
        related_document_type="APROBACION_DE_PRORROGA",
        missionary_ids=[first_id, second_id],
    )

    workspace = secretary_service.get_task_workspace(task["id"])

    assert workspace["brief_text"].startswith("Ready to review:")
    assert workspace["brief_text"].endswith("1/2 uploaded.")
    assert workspace["classification"]["document_uploaded_count"] == 1
    assert workspace["classification"]["document_missing_count"] == 1
    assert workspace["classification"]["stage_match_count"] == 1
    assert workspace["classification"]["stage_mismatch_count"] == 1
    assert any(
        fact["label"] == "Document"
        and fact["value"].endswith("1/2 uploaded")
        for fact in workspace["key_facts"]
    )
    assert any(
        person["name"] == "Ready One"
        and person["related_document_uploaded"] is True
        and person["related_stage_matches"] is True
        for person in workspace["affected_missionaries"]
    )
    assert any(
        person["name"] == "Ready Two"
        and person["related_document_uploaded"] is False
        and person["related_stage_matches"] is False
        for person in workspace["affected_missionaries"]
    )
    assert workspace["recommended_steps"][0] == (
        "Review the ready task and confirm the linked records."
    )
    assert any(
        "move the task to Waiting" in step
        for step in workspace["recommended_steps"]
    )


def test_waiting_workspace_surfaces_follow_up_date(secretary_service):
    task = secretary_service.create_task(
        "Waiting on missionary",
        status="WAITING",
        waiting_reason="MISSIONARY",
        waiting_follow_up_date=date(2026, 6, 18),
    )

    workspace = secretary_service.get_task_workspace(task["id"])

    assert "Follow up Jun 18, 2026" in workspace["why_points"]
    assert any(
        fact["label"] == "Follow-up"
        and fact["value"] == "Follow up Jun 18, 2026"
        for fact in workspace["key_facts"]
    )
    assert workspace["recommended_steps"] == [
        "Check what this task is waiting on.",
        "Use the waiting follow-up date: Follow up Jun 18, 2026.",
        "Update the waiting reason or notes if the situation changed.",
        "Mark Ready when the needed pieces are available.",
    ]


def test_waiting_follow_up_due_filter_and_summary(secretary_service, monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 18)

    monkeypatch.setattr(service_module, "date", FakeDate)

    today_due = secretary_service.create_task(
        "A follow up today",
        status="WAITING",
        waiting_reason="MISSIONARY",
        waiting_follow_up_date=FakeDate.today(),
    )
    overdue = secretary_service.create_task(
        "Z overdue follow-up",
        status="WAITING",
        waiting_reason="PAYMENT",
        waiting_follow_up_date=FakeDate.today() - timedelta(days=2),
    )
    upcoming = secretary_service.create_task(
        "Follow up later",
        status="WAITING",
        waiting_reason="DOCUMENT",
        waiting_follow_up_date=FakeDate.today() + timedelta(days=1),
    )
    missing = secretary_service.create_task(
        "Waiting without follow-up",
        status="WAITING",
        waiting_reason="OTHER",
    )
    secretary_service.create_task("Open task without follow-up")

    results = secretary_service.list_tasks(waiting_follow_up="due")
    upcoming_results = secretary_service.list_tasks(waiting_follow_up="upcoming")
    missing_results = secretary_service.list_tasks(waiting_follow_up="missing")
    summary = secretary_service.summary()
    grouped = secretary_service.grouped_tasks()

    assert [task["id"] for task in results] == [overdue["id"], today_due["id"]]
    assert [task["id"] for task in upcoming_results] == [upcoming["id"]]
    assert [task["id"] for task in missing_results] == [missing["id"]]
    assert summary["follow_up"] == 2
    assert summary["missing_follow_up"] == 1
    assert [task["id"] for task in grouped["follow_up_due"]] == [
        overdue["id"],
        today_due["id"],
    ]
    assert today_due["id"] not in [
        task["id"]
        for group_key, tasks in grouped.items()
        if group_key != "follow_up_due"
        for task in tasks
    ]
    assert overdue["id"] not in [
        task["id"]
        for group_key, tasks in grouped.items()
        if group_key != "follow_up_due"
        for task in tasks
    ]


def test_filters_by_waiting_reason(secretary_service):
    target = secretary_service.create_task(
        "Waiting on missionary",
        status="WAITING",
        waiting_reason="MISSIONARY",
    )
    secretary_service.create_task(
        "Waiting on document",
        status="WAITING",
        waiting_reason="DOCUMENT",
    )
    secretary_service.create_task("Open task")

    results = secretary_service.list_tasks(waiting_reason="MISSIONARY")

    assert [task["id"] for task in results] == [target["id"]]


def test_task_workspace_missing_task_raises(secretary_service):
    with pytest.raises(SecretaryWorkError):
        secretary_service.get_task_workspace(999)


def test_waiting_task_requires_reason_and_clears_when_reopened(secretary_service):
    with pytest.raises(SecretaryWorkError):
        secretary_service.create_task("Waiting task", status="WAITING")

    task = secretary_service.create_task(
        "Waiting task",
        status="WAITING",
        waiting_reason="DOCUMENT",
        waiting_follow_up_date=date(2026, 6, 18),
    )

    assert task["status"] == "WAITING"
    assert task["waiting_reason"] == "DOCUMENT"
    assert task["waiting_reason_label"] == "Waiting on document"
    assert task["waiting_follow_up_date"] == date(2026, 6, 18)
    assert task["waiting_follow_up_label"] == "Follow up Jun 18, 2026"

    reopened = secretary_service.update_task(task["id"], status="OPEN")

    assert reopened["status"] == "OPEN"
    assert reopened["waiting_reason"] is None
    assert reopened["waiting_reason_label"] == ""
    assert reopened["waiting_follow_up_date"] is None
    assert reopened["waiting_follow_up_label"] == ""


def test_ready_and_needs_work_transitions_clear_waiting_reason(secretary_service):
    task = secretary_service.create_task(
        "Waiting on packet",
        status="WAITING",
        waiting_reason="DOCUMENT",
        waiting_follow_up_date=date(2026, 6, 18),
    )

    ready = secretary_service.mark_task_ready(task["id"])
    reopened = secretary_service.reopen_task(task["id"])

    assert ready["status"] == "READY"
    assert ready["waiting_reason"] is None
    assert ready["waiting_follow_up_date"] is None
    assert reopened["status"] == "OPEN"
    assert reopened["waiting_reason"] is None
    assert reopened["waiting_follow_up_date"] is None


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


def test_calendar_tasks_include_done_with_work_date_but_skip_archived(secretary_service):
    visible = secretary_service.create_task("Visible", work_date=date(2026, 6, 10))
    done = secretary_service.create_task("Done", work_date=date(2026, 6, 11))
    no_work_date = secretary_service.create_task("No work date")
    archived = secretary_service.create_task("Archived", work_date=date(2026, 6, 12))
    secretary_service.complete_task(done["id"])
    secretary_service.archive_task(archived["id"])

    assert [task["title"] for task in secretary_service.list_calendar_tasks()] == [
        visible["title"],
        done["title"],
    ]


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
                "(id, title, status, priority, due_date, missionary_id) "
                "VALUES (10, 'Existing Task', 'OPEN', 'NORMAL', '2026-06-10', 5)"
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
        group_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(missionary_groups)"))
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
        indexes = {
            row[1]
            for row in conn.execute(
                text("PRAGMA index_list(secretary_task_history)")
            )
        }

    assert "waiting_reason" in columns
    assert "group_id" in columns
    assert "group_scope_label" in columns
    assert "work_date" in columns
    assert "task_type" in columns
    assert "related_stage" in columns
    assert "related_document_type" in columns
    assert "automation_key" in columns
    assert "automation_source" in columns
    assert "automation_status_reason" in columns
    assert "waiting_follow_up_date" in columns
    assert "group_type" in group_columns
    assert "automation_key" in group_columns
    assert "missionary_groups" in group_tables
    assert "missionary_group_members" in group_tables
    assert "secretary_task_missionaries" in group_tables
    assert "secretary_task_history" in group_tables
    assert "idx_secretary_task_history_task_id" in indexes
    assert backfilled_links == [(10, 5)]

    with engine.connect() as conn:
        backfilled_work_date = conn.execute(
            text("SELECT work_date FROM secretary_tasks WHERE id = 10")
        ).scalar()

    assert backfilled_work_date == "2026-06-10"


def test_project_progress_counts_tasks(secretary_service):
    project = secretary_service.create_project("Pickup week")
    open_task = secretary_service.create_task("Open", project_id=project["id"])
    ready_task = secretary_service.create_task(
        "Ready",
        status="READY",
        project_id=project["id"],
    )
    waiting_task = secretary_service.create_task(
        "Waiting",
        status="WAITING",
        waiting_reason="DOCUMENT",
        project_id=project["id"],
    )
    done_task = secretary_service.create_task("Done", project_id=project["id"])
    archived_task = secretary_service.create_task("Archived", project_id=project["id"])
    secretary_service.complete_task(done_task["id"])
    secretary_service.archive_task(archived_task["id"])

    refreshed = secretary_service.list_projects(include_done=True)[0]

    assert refreshed["open_tasks"] == 3
    assert refreshed["todo_tasks"] == 1
    assert refreshed["ready_tasks"] == 1
    assert refreshed["waiting_tasks"] == 1
    assert refreshed["done_tasks"] == 1
    assert refreshed["total_tasks"] == 4
    assert refreshed["progress"] == "1/4 done"


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
