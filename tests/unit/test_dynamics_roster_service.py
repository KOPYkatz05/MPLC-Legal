from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from database.models.missionary import Missionary
import services.dynamics_roster_service as roster_module
from services.dynamics_roster_service import (
    CENTRAL_MISSION,
    DynamicsRosterError,
    DynamicsRosterService,
    canonical_name,
)


HEADERS = [
    "(Do Not Modify) Contact", "(Do Not Modify) Row Checksum",
    "(Do Not Modify) Modified On", "Missionary ID", "Romanized Name",
    "Missionary Status", "Release Date", "Citizenship", "Mission",
    "Home Address", "Mother Name", "Father Name", "In Field Arrival Date",
]


def workbook_bytes(*rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Missionary - Active"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append([
            row.get("contact", "contact"), row.get("checksum", "sum"),
            row.get("modified", datetime(2026, 7, 30, 12)),
            row["id"], row["name"], row.get("status", "In-field"),
            row.get("release", date(2027, 1, 1)),
            row.get("citizenship", "USA"),
            row.get("mission", CENTRAL_MISSION),
            row.get("home", "Home"), row.get("mother", "Maria Smith"),
            row.get("father", "John Smith"),
            row.get("arrival", date(2026, 7, 1)),
        ])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


@pytest.fixture
def roster_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(roster_module, "SessionLocal", session_factory)
    monkeypatch.setattr(
        roster_module.OneDriveService,
        "create_missionary_folders",
        lambda _self, name: f"C:/Missionaries/{name}",
    )
    initialized = []
    monkeypatch.setattr(
        roster_module.WorkflowService,
        "initialize_workflows",
        lambda _self, missionary_id: initialized.append(missionary_id),
    )
    monkeypatch.setattr(
        roster_module.DynamicsRosterService,
        "_reconcile_automation",
        staticmethod(lambda: None),
    )
    return session_factory, initialized


def add_missionary(session_factory, **values):
    session = session_factory()
    missionary = Missionary(
        full_name=values.pop("full_name", "Smith, John"),
        missionary_code=values.pop("missionary_code", "M1"),
        status=values.pop("status", "ACTIVE"),
        current_stage=values.pop("current_stage", "INTERPOL"),
        tracking_profile=values.pop("tracking_profile", "LEGAL"),
        **values,
    )
    session.add(missionary)
    session.commit()
    session.refresh(missionary)
    missionary_id = missionary.id
    session.close()
    return missionary_id


def test_canonical_name_ignores_order_accents_and_punctuation():
    assert canonical_name("Pérez, José Luis") == canonical_name("LUIS JOSE PEREZ")
    assert canonical_name("Jose Perez") != canonical_name("Jose Luis Perez")


def test_new_peruvian_import_is_complete_before_flush_and_has_no_workflow(roster_db):
    session_factory, initialized = roster_db
    content = workbook_bytes(
        {"id": "P1", "name": "Quispe, Ana", "citizenship": "Peru"}
    )
    service = DynamicsRosterService()
    preview = service.preview(content, "Missionary - Active 30-Jul-26 4-09-01 PM.xlsx")
    result = service.apply(content, "same.xlsx", preview["preview_id"], {})

    assert result["created"] == 1
    session = session_factory()
    missionary = session.query(Missionary).one()
    assert missionary.full_name == "Quispe, Ana"
    assert missionary.current_stage == "DNI"
    assert missionary.tracking_profile == "PERUVIAN_DNI"
    assert initialized == []
    session.close()


def test_roster_import_collapses_repeated_name_whitespace(roster_db):
    session_factory, _ = roster_db
    content = workbook_bytes(
        {"id": "M1", "name": "  Smith,  Jane\tMarie  "}
    )
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    service.apply(content, "roster.xlsx", preview["preview_id"], {})

    session = session_factory()
    assert session.query(Missionary).one().full_name == "Smith, Jane Marie"
    session.close()


def test_same_id_different_name_requires_explicit_resolution(roster_db):
    session_factory, _ = roster_db
    missionary_id = add_missionary(
        session_factory, missionary_code="M1", full_name="Smith, John"
    )
    content = workbook_bytes({"id": "M1", "name": "Jones, Robert"})
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    assert preview["conflicts"][0]["kind"] == "ID_CONFLICT"
    assert "_rows" not in preview
    with pytest.raises(DynamicsRosterError, match="Resolve every"):
        service.apply(content, "roster.xlsx", preview["preview_id"], {})
    result = service.apply(
        content, "roster.xlsx", preview["preview_id"],
        {str(preview["conflicts"][0]["row"]): "same"},
    )
    assert result["updated"] == 1
    session = session_factory()
    assert session.get(Missionary, missionary_id).full_name == "Jones, Robert"
    session.close()


def test_name_match_different_id_never_creates_duplicate_when_same(roster_db):
    session_factory, _ = roster_db
    missionary_id = add_missionary(
        session_factory, missionary_code="OLD", full_name="Pérez, José Luis"
    )
    content = workbook_bytes({"id": "NEW", "name": "LUIS JOSE PEREZ"})
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    conflict = preview["conflicts"][0]
    assert conflict["kind"] == "POSSIBLE_DUPLICATE"
    service.apply(
        content, "roster.xlsx", preview["preview_id"],
        {str(conflict["row"]): "same"},
    )
    session = session_factory()
    assert session.query(Missionary).count() == 1
    assert session.get(Missionary, missionary_id).missionary_code == "NEW"
    session.close()


def test_inactive_exact_match_requires_restore_or_skip(roster_db):
    session_factory, _ = roster_db
    missionary_id = add_missionary(
        session_factory, status="ARCHIVED", missionary_code="M1",
        full_name="Smith, John",
    )
    content = workbook_bytes({"id": "M1", "name": "John Smith"})
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    conflict = preview["conflicts"][0]
    assert conflict["kind"] == "INACTIVE_MATCH"
    service.apply(
        content, "roster.xlsx", preview["preview_id"],
        {str(conflict["row"]): "restore"},
    )
    session = session_factory()
    assert session.get(Missionary, missionary_id).status == "ACTIVE"
    session.close()


def test_duplicate_source_ids_and_changed_file_hash_block_apply(roster_db):
    _session_factory, _ = roster_db
    duplicate = workbook_bytes(
        {"id": "M1", "name": "One"}, {"id": "M1", "name": "Two"}
    )
    service = DynamicsRosterService()
    preview = service.preview(duplicate, "roster.xlsx")
    assert len(preview["invalid"]) == 2
    with pytest.raises(DynamicsRosterError, match="Correct invalid"):
        service.apply(duplicate, "roster.xlsx", preview["preview_id"], {})

    original = workbook_bytes({"id": "M2", "name": "Original Person"})
    changed = workbook_bytes({"id": "M2", "name": "Changed Person"})
    preview = service.preview(original, "roster.xlsx")
    with pytest.raises(DynamicsRosterError, match="changed after preview"):
        service.apply(changed, "roster.xlsx", preview["preview_id"], {})


def test_unchanged_existing_record_is_not_counted_as_updated(roster_db):
    session_factory, _ = roster_db
    row = {"id": "M1", "name": "Smith, John"}
    add_missionary(
        session_factory,
        missionary_code="M1", full_name="Smith, John",
        nationality="USA", arrival_date=date(2026, 7, 1),
        release_date=date(2027, 1, 1), dynamics_status="In-field",
        home_address="Home", mother_name="Maria Smith",
        father_name="John Smith", dynamics_contact_id="contact",
        dynamics_row_checksum="sum",
        dynamics_modified_at=datetime(2026, 7, 30, 12),
    )
    content = workbook_bytes(row)
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    assert len(preview["unchanged"]) == 1
    result = service.apply(content, "roster.xlsx", preview["preview_id"], {})
    assert result["updated"] == 0
    assert result["unchanged_count"] == 1
    assert service.last_import()["filename"] == "roster.xlsx"


def test_apply_rolls_back_database_when_creation_fails(roster_db, monkeypatch):
    session_factory, _ = roster_db
    content = workbook_bytes({"id": "M1", "name": "Rollback Person"})
    service = DynamicsRosterService()
    preview = service.preview(content, "roster.xlsx")
    monkeypatch.setattr(
        roster_module.OneDriveService,
        "create_missionary_folders",
        lambda *_args: (_ for _ in ()).throw(OSError("folder failure")),
    )
    with pytest.raises(OSError, match="folder failure"):
        service.apply(content, "roster.xlsx", preview["preview_id"], {})
    session = session_factory()
    assert session.query(Missionary).count() == 0
    session.close()
