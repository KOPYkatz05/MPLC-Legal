import json
from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QDate
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from services import upload_pipeline
from ui.pages import missionary_detail_page as detail_module


def test_passport_upload_auto_updates_birthdate_and_source(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(upload_pipeline, "SessionLocal", testing_session)

    session = testing_session()
    missionary = Missionary(full_name="Test Missionary")
    session.add(missionary)
    session.commit()
    missionary_id = missionary.id
    session.close()

    updated = upload_pipeline.apply_missionary_updates(
        missionary_id,
        "PASSPORT",
        77,
        {
            "date_of_birth": "1990-02-03",
            "passport_number": "P1234567",
        },
    )

    session = testing_session()
    try:
        refreshed = session.query(Missionary).filter_by(id=missionary_id).one()
        sources = json.loads(refreshed.field_sources)

        assert "date_of_birth" in updated
        assert refreshed.date_of_birth == date(1990, 2, 3)
        assert sources["date_of_birth"] == {
            "document_id": 77,
            "document_type": "PASSPORT",
            "label": "Passport",
        }
    finally:
        session.close()


def test_missionary_detail_page_handles_birthdate_field(monkeypatch, qapp):
    page = detail_module.MissionaryDetailPage(
        SimpleNamespace(
            stack=SimpleNamespace(
                widget=lambda *_: None,
                setCurrentIndex=lambda *_: None,
            ),
            calendar_page=None,
        )
    )

    monkeypatch.setattr(
        page.workflow_service,
        "get_workflows",
        lambda *_: [],
    )
    monkeypatch.setattr(
        page.document_service,
        "get_documents",
        lambda *_: [],
    )
    monkeypatch.setattr(
        page,
        "_refresh_residency_timeline",
        lambda *_: None,
    )
    monkeypatch.setattr(
        page,
        "_refresh_overview_summary",
        lambda *_: None,
    )
    monkeypatch.setattr(page, "_load_timeline", lambda *_: None)
    monkeypatch.setattr(page, "_update_advance_banner", lambda *_: None)

    missionary = SimpleNamespace(
        id=1,
        full_name="Test Missionary",
        current_stage="INTERPOL",
        nationality="USA",
        passport_number="P1234567",
        date_of_birth=date(1990, 2, 3),
        field_sources=json.dumps(
            {
                "date_of_birth": {
                    "document_id": 77,
                    "document_type": "PASSPORT",
                    "label": "Passport",
                }
            }
        ),
        folder_path=None,
        notes="",
        arrival_date=None,
        visa_expiration=None,
        residency_expiration=None,
        prorroga_expiration=None,
        carnet_issue_date=None,
        cancelacion_date=None,
        passport_expiration=None,
        interpol_appointment_date=None,
        biometric_appointment_date=None,
        pickup_appointment_date=None,
        tramite_usuario=None,
        tramite_contrasena=None,
    )

    page.load_missionary(missionary)

    def _picker_date(edit):
        return edit.getDate() if hasattr(edit, "getDate") else edit.date

    assert "date_of_birth" in page._date_edits
    assert _picker_date(page._date_edits["date_of_birth"]) == QDate(
        1990,
        2,
        3,
    )
    if hasattr(page._date_edits["date_of_birth"], "specialValueText"):
        assert (
            page._date_edits["date_of_birth"].specialValueText()
            == "Not set"
        )
    arrival_picker = page._date_edits["arrival_date"]
    assert arrival_picker.property("state") == "empty"
    assert page._date_empty_overlays[arrival_picker].text() == "Not set"
    fluent_buttons = [
        child.text()
        for child in arrival_picker.children()
        if child.objectName() == "pickerButton"
        and hasattr(child, "text")
    ]
    if fluent_buttons:
        assert fluent_buttons == ["Not set", "", ""]
    assert "Passport" in page._date_source_labels["date_of_birth"].text()
    assert page.folder_open_btn.isEnabled() is False
    assert "Name:" in page.summary_name_chip.text()
    assert "Birthdate:" in page.summary_birthdate_chip.text()

    captured = {}

    def capture_update_fields(missionary_id, updates):
        captured["missionary_id"] = missionary_id
        captured["updates"] = updates

    monkeypatch.setattr(
        page.missionary_service,
        "update_fields",
        capture_update_fields,
    )
    monkeypatch.setattr(detail_module, "show_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(page, "_reload_missionary", lambda: None)

    page._date_edits["date_of_birth"].setDate(QDate(1991, 4, 5))
    page._save_dates()

    assert captured["missionary_id"] == 1
    assert captured["updates"]["date_of_birth"] == date(1991, 4, 5)


def test_run_migrations_adds_birthdate_column(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE missionaries (
                    id INTEGER PRIMARY KEY,
                    missionary_code TEXT,
                    status VARCHAR,
                    full_name VARCHAR NOT NULL
                )
                """
            )
        )

    from database import db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    db_module._run_migrations()

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(missionaries)"))
        }

    assert "date_of_birth" in columns
