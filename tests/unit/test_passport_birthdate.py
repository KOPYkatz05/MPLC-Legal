import json
from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QDate
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from services.api_client import RemoteRecord
from services import upload_pipeline
from ui.pages import missionary_detail_page as detail_module


def test_detail_back_delegates_to_the_single_window_confirmation():
    calls = []
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.main_window = SimpleNamespace(
        return_from_missionary_detail=lambda: calls.append("return")
    )
    page.confirm_leave_detail = lambda: (_ for _ in ()).throw(
        AssertionError("The detail page must not confirm twice")
    )

    page._go_back()

    assert calls == ["return"]


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


def test_passport_upload_removes_whitespace_from_passport_number(monkeypatch):
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

    upload_pipeline.apply_missionary_updates(
        missionary_id,
        "PASSPORT",
        77,
        {"passport_number": "P12 34\t567"},
    )

    session = testing_session()
    try:
        refreshed = session.query(Missionary).filter_by(id=missionary_id).one()
        assert refreshed.passport_number == "P1234567"
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
        page.secretary_work_service,
        "list_tasks",
        lambda *_args, **_kwargs: [],
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

    missionary = RemoteRecord(
        {
            "id": 1,
            "full_name": "Test Missionary",
            "current_stage": "INTERPOL",
            "nationality": "USA",
            "passport_number": "P1234567",
            "date_of_birth": "1990-02-03",
            "field_sources": json.dumps(
                {
                    "date_of_birth": {
                        "document_id": 77,
                        "document_type": "PASSPORT",
                        "label": "Passport",
                    }
                }
            ),
            "folder_path": None,
            "notes": "",
            "arrival_date": None,
            "release_date": "2027-01-15",
            "visa_expiration": None,
            "residency_expiration": None,
            "prorroga_expiration": None,
            "carnet_issue_date": None,
            "cancelacion_date": None,
            "passport_expiration": None,
            "interpol_appointment_date": None,
            "biometric_appointment_date": None,
            "pickup_appointment_date": None,
            "tramite_usuario": None,
            "tramite_contrasena": None,
            "carnet_number": None,
            "home_address": "123 Home Street",
            "father_name": "Carlos Example",
            "mother_name": "Maria Example",
            "father_first_name_override": None,
            "mother_first_name_override": None,
        }
    )

    page.load_missionary(missionary)

    def _picker_date(edit):
        return edit.getDate() if hasattr(edit, "getDate") else edit.date

    assert "date_of_birth" in page._date_edits
    assert "release_date" in page._date_edits
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
    assert _picker_date(page._date_edits["release_date"]) == QDate(
        2027,
        1,
        15,
    )
    assert page.home_address_input.text() == "123 Home Street"
    assert page.full_name_input.text() == "Test Missionary"
    assert page.passport_input.text() == "P1234567"
    assert page.father_name_input.text() == "Carlos Example"
    assert page.mother_name_input.text() == "Maria Example"
    assert page.folder_open_btn.isEnabled() is False
    assert "Name:" in page.summary_name_chip.text()
    assert "Birthdate:" in page.summary_birthdate_chip.text()
    assert page.has_unsaved_changes() is False
    assert page._detail_loaded is True
    assert page.detail_loading_icon.isHidden()

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
    page.carnet_number_input.setText("CE123456")
    page._date_edits["release_date"].setDate(QDate(2027, 2, 20))
    page.home_address_input.setText("Updated Home Address")
    page.full_name_input.setText("Updated Missionary")
    page.passport_input.setText("P12 34 567")
    page.father_name_input.setText("Carlos Updated")
    page.mother_name_input.setText("Maria Updated")
    page.tramite_usuario_input.setText("reset-user")
    page.tramite_contrasena_input.setText("reset-pass")
    page._save_dates()

    assert captured["missionary_id"] == 1
    assert captured["updates"]["date_of_birth"] == date(1991, 4, 5)
    assert captured["updates"]["carnet_number"] == "CE123456"
    assert captured["updates"]["release_date"] == date(2027, 2, 20)
    assert captured["updates"]["home_address"] == "Updated Home Address"
    assert captured["updates"]["full_name"] == "Updated Missionary"
    assert captured["updates"]["passport_number"] == "P1234567"
    assert captured["updates"]["father_name"] == "Carlos Updated"
    assert captured["updates"]["mother_name"] == "Maria Updated"
    assert captured["updates"]["tramite_usuario"] == "reset-user"
    assert captured["updates"]["tramite_contrasena"] == "reset-pass"


def test_missionary_detail_lists_open_tasks(monkeypatch, qapp):
    page = detail_module.MissionaryDetailPage(
        SimpleNamespace(
            stack=SimpleNamespace(
                setCurrentIndex=lambda *_: None,
            ),
            sidebar=SimpleNamespace(setCurrentRow=lambda *_: None),
            office_work_page=SimpleNamespace(load_data=lambda: None),
            calendar_page=SimpleNamespace(load_data=lambda: None),
        )
    )

    try:
        page.current_missionary = SimpleNamespace(id=1)
        monkeypatch.setattr(
            page.secretary_work_service,
            "list_tasks",
            lambda **kwargs: [
                {
                    "id": 10,
                    "title": "Call mission office",
                    "status": "WAITING",
                    "priority": "IMPORTANT",
                    "due_date": date(2026, 6, 12),
                    "waiting_reason_label": "Waiting on document",
                }
            ]
            if kwargs.get("missionary_id") == 1
            else [],
        )

        page.load_open_tasks()

        assert page.open_tasks_list.count() == 1
        widget = page.open_tasks_list.itemWidget(page.open_tasks_list.item(0))
        assert widget is not None
        labels = widget.findChildren(detail_module.QLabel)
        assert any(label.text() == "Call mission office" for label in labels)
    finally:
        page.close()


def test_missionary_detail_add_task_preselects_missionary(monkeypatch, qapp):
    captured = []

    class FakeTaskDialog:
        def __init__(self, service, task=None, defaults=None, parent=None):
            captured.append(
                {
                    "service": service,
                    "task": task,
                    "defaults": defaults,
                    "parent": parent,
                }
            )

        def exec(self):
            return False

    page = detail_module.MissionaryDetailPage(
        SimpleNamespace(
            stack=SimpleNamespace(
                setCurrentIndex=lambda *_: None,
            ),
            sidebar=SimpleNamespace(setCurrentRow=lambda *_: None),
            office_work_page=SimpleNamespace(load_data=lambda: None),
            calendar_page=SimpleNamespace(load_data=lambda: None),
        )
    )

    try:
        page.current_missionary = SimpleNamespace(id=7)
        monkeypatch.setattr(detail_module, "TaskDialog", FakeTaskDialog)

        page._add_missionary_task()

        assert captured[-1]["defaults"] == {"missionary_id": 7}
        assert captured[-1]["parent"] is page
    finally:
        page.close()


def test_interpol_packet_opens_with_default_pdf_viewer(monkeypatch):
    opened = []
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )

    monkeypatch.setattr(
        detail_module,
        "open_document_with_default_app",
        lambda file_path: opened.append(file_path),
    )

    page._open_packet_in_default_pdf_viewer("C:/Temp/interpol_packet.pdf")

    assert opened == ["C:/Temp/interpol_packet.pdf"]


def test_print_interpol_packet_uses_default_viewer_after_build(monkeypatch):
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.current_missionary = SimpleNamespace(id=7)
    calls = []

    monkeypatch.setattr(
        page,
        "_validated_interpol_annotation_lines",
        lambda: ["complete"],
    )
    monkeypatch.setattr(
        page,
        "_collect_interpol_packet_docs",
        lambda: ([{"label": "Passport", "file_path": "passport.pdf"}], []),
    )
    monkeypatch.setattr(
        page,
        "_create_interpol_packet_temp_path",
        lambda: "C:/Temp/interpol_packet.pdf",
    )
    monkeypatch.setattr(
        page,
        "_build_interpol_packet_pdf",
        lambda docs, output_path:
        calls.append(("build", docs, output_path)),
    )
    monkeypatch.setattr(
        page,
        "_open_packet_in_default_pdf_viewer",
        lambda packet_path: calls.append(("open", packet_path)),
    )

    page._print_interpol_packet()

    assert calls == [
        (
            "build",
            [{"label": "Passport", "file_path": "passport.pdf"}],
            "C:/Temp/interpol_packet.pdf",
        ),
        ("open", "C:/Temp/interpol_packet.pdf"),
    ]


def test_interpol_annotation_uses_ordered_labels_and_blank_name_override(
    monkeypatch,
):
    from server import configuration as configuration_module

    monkeypatch.setattr(
        configuration_module,
        "load_server_configuration",
        lambda: {
            "interpol_area_office_address": "Area Office",
            "interpol_secretary_phone": "999-111-222",
        },
    )
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.document_service = SimpleNamespace(api_client=None)
    page.current_missionary = SimpleNamespace(
        home_address="Home Address",
        father_name="",
        father_first_name_override="Carlos",
        mother_name="Maria Smith",
        mother_first_name_override="",
    )

    assert page._validated_interpol_annotation_lines() == [
        "Dirección Actual: Area Office",
        "Dirección en País de Origen: Home Address",
        "Nombre de Padre: Carlos",
        "Nombre de Madre: Maria",
        "Teléfono: 999-111-222",
    ]


def test_interpol_annotation_blocks_missing_official_data(monkeypatch):
    import pytest
    from server import configuration as configuration_module

    monkeypatch.setattr(
        configuration_module,
        "load_server_configuration",
        lambda: {},
    )
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.document_service = SimpleNamespace(api_client=None)
    page.current_missionary = SimpleNamespace(
        home_address="", father_name="", mother_name="",
        father_first_name_override="", mother_first_name_override="",
    )
    with pytest.raises(ValueError, match="Area Office address"):
        page._validated_interpol_annotation_lines()


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
    assert "carnet_number" in columns
