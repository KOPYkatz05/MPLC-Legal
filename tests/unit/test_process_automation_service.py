from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import (
    MissionaryGroup,
    MissionaryGroupMember,
    SecretaryTask,
    SecretaryTaskMissionary,
)
from services import process_automation_service as automation_module
from services import secretary_work_service as secretary_module
from services.process_automation_service import ProcessAutomationService
from services.secretary_work_service import SecretaryWorkService


class FakeSettings:
    def __init__(self, transfers=None):
        self.transfers = transfers or []

    def get_upcoming_transfer_wednesdays(self, *, today=None, count=8):
        return list(self.transfers[:count])


@pytest.fixture()
def automation_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(automation_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(secretary_module, "SessionLocal", TestingSession)
    return TestingSession


def _service(settings=None):
    return ProcessAutomationService(
        settings_service=settings or FakeSettings(),
        secretary_work_service=SecretaryWorkService(),
    )


def _missionary(session, **fields):
    missionary = Missionary(
        missionary_code=fields.pop("missionary_code", "10001"),
        full_name=fields.pop("full_name", "Test Missionary"),
        status=fields.pop("status", "ACTIVE"),
        current_stage=fields.pop("current_stage", "INTERPOL"),
        **fields,
    )
    session.add(missionary)
    session.flush()
    return missionary


def _document(session, missionary_id, document_type):
    session.add(
        Document(
            missionary_id=missionary_id,
            document_type=document_type,
            workflow_stage="TEST",
            status="ACTIVE",
            file_name=f"{document_type}.pdf",
            file_path=f"/tmp/{document_type}.pdf",
        )
    )


def _tasks(session):
    return session.query(SecretaryTask).order_by(SecretaryTask.title).all()


def test_automation_is_idempotent(automation_env):
    session = automation_env()
    try:
        _missionary(
            session,
            residency_expiration=date(2026, 8, 15),
        )
        session.commit()
    finally:
        session.close()

    service = _service()
    today = date(2026, 6, 20)

    first = service.run(today=today)
    second = service.run(today=today)

    session = automation_env()
    try:
        assert session.query(SecretaryTask).count() == first["created"]
        assert second["created"] == 0
        assert second["updated"] == first["created"]
    finally:
        session.close()


def test_completed_automatic_task_is_not_recreated(automation_env):
    session = automation_env()
    try:
        missionary = _missionary(session)
        _document(session, missionary.id, "CARNE_DE_EXTRANJERIA")
        session.commit()
    finally:
        session.close()

    service = _service()
    service.run(today=date(2026, 6, 20))

    work = SecretaryWorkService()
    task = work.list_tasks()[0]
    work.complete_task(task["id"])
    result = service.run(today=date(2026, 6, 20))

    session = automation_env()
    try:
        tasks = _tasks(session)
        assert len(tasks) == 1
        assert tasks[0].status == "DONE"
        assert result["skipped"] == 1
    finally:
        session.close()


def test_transfer_reminders_require_configured_transfer_date(automation_env):
    today = date(2026, 6, 20)
    configured = _service(FakeSettings([date(2026, 7, 29)]))
    unconfigured = _service(FakeSettings([]))

    assert unconfigured.run(today=today)["created"] == 0

    configured.run(today=today)
    session = automation_env()
    try:
        tasks = {task.automation_key: task for task in _tasks(session)}
        assert "transfer:fbi:2026-07-29" in tasks
        assert "transfer:flights:2026-07-29" in tasks
        assert tasks["transfer:fbi:2026-07-29"].due_date == date(2026, 7, 15)
        assert tasks["transfer:flights:2026-07-29"].due_date == date(2026, 4, 30)
    finally:
        session.close()


def test_prorroga_windows_generate_from_residency_expiration(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        _missionary(session, residency_expiration=expiration)
        session.commit()
    finally:
        session.close()

    _service().run(today=expiration - timedelta(days=61))

    session = automation_env()
    try:
        assert _tasks(session) == []
    finally:
        session.close()

    _service().run(today=expiration - timedelta(days=60))
    session = automation_env()
    try:
        tasks = _tasks(session)
        assert [task.automation_key for task in tasks] == [
            "prorroga:1:60:2026-09-08"
        ]
        assert tasks[0].title == "Prorroga submission window is open"
    finally:
        session.close()


def test_transfer_reminders_only_generate_for_next_cycle(automation_env):
    today = date(2026, 6, 20)
    service = _service(FakeSettings([
        date(2026, 7, 29),
        date(2026, 9, 9),
        date(2026, 10, 21),
    ]))

    service.run(today=today)

    session = automation_env()
    try:
        transfer_keys = {
            task.automation_key
            for task in _tasks(session)
            if task.automation_key.startswith("transfer:")
        }
        assert transfer_keys == {
            "transfer:fbi:2026-07-29",
            "transfer:flights:2026-07-29",
            "transfer:arrivals:2026-07-29",
        }
    finally:
        session.close()


def test_prorroga_uses_only_current_strongest_window(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        _missionary(session, residency_expiration=expiration)
        session.commit()
    finally:
        session.close()

    service = _service()

    service.run(today=expiration - timedelta(days=60))
    session = automation_env()
    try:
        assert {
            task.automation_key: task.status
            for task in _tasks(session)
        } == {"prorroga:1:60:2026-09-08": "OPEN"}
    finally:
        session.close()

    service.run(today=expiration - timedelta(days=30))
    session = automation_env()
    try:
        statuses = {
            task.automation_key: task.status
            for task in _tasks(session)
        }
        assert statuses["prorroga:1:60:2026-09-08"] == "ARCHIVED"
        assert statuses["prorroga:1:30:2026-09-08"] == "OPEN"
    finally:
        session.close()


def test_prorroga_windows_group_missionaries_in_same_week(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        first = _missionary(
            session,
            missionary_code="first",
            full_name="Elder First",
            residency_expiration=expiration,
        )
        second = _missionary(
            session,
            missionary_code="second",
            full_name="Sister Second",
            residency_expiration=expiration + timedelta(days=2),
        )
        session.commit()
        first_id = first.id
        second_id = second.id
    finally:
        session.close()

    _service().run(today=expiration - timedelta(days=28))

    session = automation_env()
    try:
        tasks = _tasks(session)
        grouped_task = next(
            task
            for task in tasks
            if task.automation_key == "prorroga:group:30:2026-08-09"
        )
        assert grouped_task.group_id is not None
        assert grouped_task.missionary_id is None
        assert grouped_task.group_scope_label.startswith("Temporary - ")

        task_links = (
            session.query(SecretaryTaskMissionary.missionary_id)
            .filter_by(task_id=grouped_task.id)
            .all()
        )
        group_links = (
            session.query(MissionaryGroupMember.missionary_id)
            .filter_by(group_id=grouped_task.group_id)
            .all()
        )
        assert {row[0] for row in task_links} == {first_id, second_id}
        assert {row[0] for row in group_links} == {first_id, second_id}
        assert (
            session.query(MissionaryGroup)
            .filter_by(id=grouped_task.group_id)
            .count()
            == 1
        )
    finally:
        session.close()


def test_completed_grouped_automation_removes_temporary_group(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        _missionary(
            session,
            missionary_code="first",
            residency_expiration=expiration,
        )
        _missionary(
            session,
            missionary_code="second",
            residency_expiration=expiration + timedelta(days=2),
        )
        session.commit()
    finally:
        session.close()

    _service().run(today=expiration - timedelta(days=28))
    work = SecretaryWorkService()
    grouped = next(
        task
        for task in work.list_tasks()
        if task["automation_key"] == "prorroga:group:30:2026-08-09"
    )
    group_id = grouped["group_id"]

    completed = work.complete_task(grouped["id"])

    session = automation_env()
    try:
        assert completed["status"] == "DONE"
        assert session.query(MissionaryGroup).filter_by(id=group_id).count() == 0
        task = session.query(SecretaryTask).filter_by(id=grouped["id"]).one()
        assert task.group_id is None
        links = (
            session.query(SecretaryTaskMissionary.missionary_id)
            .filter_by(task_id=grouped["id"])
            .all()
        )
        assert len(links) == 2
    finally:
        session.close()


def test_deleting_grouped_automation_removes_temporary_group(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        _missionary(
            session,
            missionary_code="first",
            residency_expiration=expiration,
        )
        _missionary(
            session,
            missionary_code="second",
            residency_expiration=expiration + timedelta(days=2),
        )
        session.commit()
    finally:
        session.close()

    _service().run(today=expiration - timedelta(days=28))
    work = SecretaryWorkService()
    grouped = next(
        task
        for task in work.list_tasks()
        if task["automation_key"] == "prorroga:group:30:2026-08-09"
    )
    group_id = grouped["group_id"]

    assert work.delete_task(grouped["id"]) is True

    session = automation_env()
    try:
        assert session.query(MissionaryGroup).filter_by(id=group_id).count() == 0
        assert session.query(SecretaryTask).filter_by(id=grouped["id"]).count() == 0
    finally:
        session.close()


def test_prorroga_not_generated_without_residency_expiration(automation_env):
    session = automation_env()
    try:
        _missionary(session)
        session.commit()
    finally:
        session.close()

    _service().run(today=date(2026, 6, 20))

    session = automation_env()
    try:
        assert session.query(SecretaryTask).count() == 0
    finally:
        session.close()


def test_cancelacion_starts_exactly_21_days_before_release(automation_env):
    release = date(2026, 10, 1)
    session = automation_env()
    try:
        _missionary(session, release_date=release, dynamics_status="In-field")
        session.commit()
    finally:
        session.close()

    service = _service()
    service.run(today=release - timedelta(days=22))
    session = automation_env()
    try:
        assert not any(
            (task.automation_key or "").startswith("cancelacion:")
            for task in _tasks(session)
        )
    finally:
        session.close()

    service.run(today=release - timedelta(days=21))
    session = automation_env()
    try:
        assert any(
            task.automation_key == "cancelacion:1:2026-10-01"
            for task in _tasks(session)
        )
    finally:
        session.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"dynamics_status": "Delay"},
        {"dynamics_status": "In-field", "tracking_profile": "PERUVIAN_DNI"},
    ],
)
def test_delay_and_peruvian_profiles_have_no_legal_automation(
    automation_env, fields
):
    session = automation_env()
    try:
        _missionary(
            session,
            residency_expiration=date(2026, 8, 1),
            release_date=date(2026, 8, 1),
            **fields,
        )
        session.commit()
    finally:
        session.close()
    _service().run(today=date(2026, 7, 15))
    session = automation_env()
    try:
        assert not [
            task for task in _tasks(session)
            if (task.automation_key or "").startswith(
                ("prorroga:", "cancelacion:", "after-", "gvm:")
            )
        ]
    finally:
        session.close()

def test_obsolete_prorroga_archives_after_approval_document(automation_env):
    expiration = date(2026, 9, 8)
    session = automation_env()
    try:
        missionary = _missionary(session, residency_expiration=expiration)
        session.commit()
        missionary_id = missionary.id
    finally:
        session.close()

    service = _service()
    service.run(today=expiration - timedelta(days=60))

    session = automation_env()
    try:
        _document(session, missionary_id, "APROBACION_DE_PRORROGA")
        session.commit()
    finally:
        session.close()

    result = service.run(today=expiration - timedelta(days=60))

    session = automation_env()
    try:
        tasks = {
            task.automation_key: task
            for task in _tasks(session)
        }
        assert tasks["prorroga:1:60:2026-09-08"].status == "ARCHIVED"
        assert tasks["prorroga:1:60:2026-09-08"].automation_status_reason
        assert tasks["gvm:prorroga:1"].status == "OPEN"
        assert result["archived_obsolete"] == 1
    finally:
        session.close()


def test_transfer_tasks_are_archived_when_cycle_is_no_longer_next(automation_env):
    first_service = _service(FakeSettings([date(2026, 7, 29)]))
    first_service.run(today=date(2026, 6, 20))

    second_service = _service(FakeSettings([date(2026, 9, 9)]))
    result = second_service.run(today=date(2026, 7, 30))

    session = automation_env()
    try:
        transfer_tasks = {
            task.automation_key: task
            for task in _tasks(session)
            if task.automation_key.startswith("transfer:")
        }
        old_tasks = [
            task
            for key, task in transfer_tasks.items()
            if key.endswith("2026-07-29")
        ]
        next_tasks = [
            task
            for key, task in transfer_tasks.items()
            if key.endswith("2026-09-09")
        ]
        assert len(old_tasks) == 3
        assert {task.status for task in old_tasks} == {"ARCHIVED"}
        assert len(next_tasks) == 3
        assert {task.status for task in next_tasks} == {"OPEN"}
        assert result["archived_obsolete"] == 3
    finally:
        session.close()


def test_gvm_task_remains_active_until_manually_completed(automation_env):
    session = automation_env()
    try:
        missionary = _missionary(session)
        _document(session, missionary.id, "CARNE_DE_EXTRANJERIA")
        session.commit()
    finally:
        session.close()

    service = _service()
    service.run(today=date(2026, 6, 20))

    session = automation_env()
    try:
        document = session.query(Document).one()
        document.status = "INACTIVE"
        session.commit()
    finally:
        session.close()

    service.run(today=date(2026, 6, 21))

    session = automation_env()
    try:
        task = session.query(SecretaryTask).filter_by(
            automation_key="gvm:carne:1"
        ).one()
        assert task.status == "OPEN"
    finally:
        session.close()


def test_gvm_tasks_follow_documents_and_stop_when_done(automation_env):
    session = automation_env()
    try:
        missionary = _missionary(session)
        for document_type in [
            "CARNE_DE_EXTRANJERIA",
            "APROBACION_DE_PRORROGA",
            "CONSTANCIA_CANCELACION",
        ]:
            _document(session, missionary.id, document_type)
        session.commit()
    finally:
        session.close()

    service = _service()
    service.run(today=date(2026, 6, 20))

    work = SecretaryWorkService()
    tasks = work.list_tasks()
    assert {
        task["automation_key"]
        for task in tasks
    } == {
        "gvm:carne:1",
        "gvm:prorroga:1",
        "gvm:cancelacion:1",
    }

    for task in tasks:
        work.complete_task(task["id"])

    service.run(today=date(2026, 6, 20))

    session = automation_env()
    try:
        assert session.query(SecretaryTask).count() == 3
        assert {
            task.status
            for task in session.query(SecretaryTask).all()
        } == {"DONE"}
    finally:
        session.close()


def test_after_event_guidance_creates_follow_up_tasks(automation_env):
    today = date(2026, 6, 20)
    session = automation_env()
    try:
        _missionary(
            session,
            interpol_appointment_date=today - timedelta(days=1),
            biometric_appointment_date=today - timedelta(days=2),
        )
        session.commit()
    finally:
        session.close()

    _service().run(today=today)

    session = automation_env()
    try:
        keys = {task.automation_key for task in _tasks(session)}
        assert "after-interpol:ficha:1:2026-06-19" in keys
        assert "after-biometric:buzon:1:2026-W25" in keys
    finally:
        session.close()
