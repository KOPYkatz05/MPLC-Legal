import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.missionary import Missionary
from services.document_parser import DocumentParser
from services import upload_pipeline
from ui.dialogs.upload_session_dialog import UploadSessionController
from services.upload_pipeline import UploadPipelineResult
from utils.constants import DOCUMENTS


def test_dni_document_enables_number_ocr_and_auto_update():
    assert DOCUMENTS["DNI"]["ocr_fields"] == ["dni_number"]
    assert DOCUMENTS["DNI"]["auto_updates"] == ["dni_number"]


def test_dni_parser_extracts_labeled_number():
    text = """
    REPUBLICA DEL PERU
    DOCUMENTO NACIONAL DE IDENTIDAD
    DNI N° 12345678
    Fecha de nacimiento 12/03/1999
    """

    assert DocumentParser().parse(text, "DNI") == {
        "dni_number": "12345678"
    }


def test_dni_parser_extracts_peruvian_mrz_number():
    text = "I<PER87654321<4<<<<<<<<<<<<<<<"

    assert DocumentParser().parse(text, "DNI") == {
        "dni_number": "87654321"
    }


def test_dni_parser_normalizes_digit_grouping():
    assert DocumentParser().parse("CUI: 12 345 678", "DNI") == {
        "dni_number": "12345678"
    }


def test_dni_parser_does_not_treat_dates_as_dni_numbers():
    text = "Fecha de nacimiento 12/03/1999\nCaducidad 18/11/2030"

    assert DocumentParser().parse(text, "DNI") == {}


def test_dni_ocr_replaces_unchanged_prefill_but_preserves_manual_edit():
    missionary = type(
        "MissionaryStub",
        (),
        {"id": 42, "full_name": "Peruvian Example", "dni_number": "11112222"},
    )()
    controller = UploadSessionController(missionary)
    controller.add_files(["dni.pdf"])
    controller.set_document_type(0, "DNI")
    item = controller.items[0]
    item.ocr_result = UploadPipelineResult(
        parsed_data={"dni_number": "33334444"}
    )

    controller.merge_ocr_data_into_confirmed(item)
    assert item.confirmed_data["dni_number"] == "33334444"

    item.confirmed_data["dni_number"] = "55556666"
    item.ocr_result = UploadPipelineResult(
        parsed_data={"dni_number": "77778888"}
    )
    controller.merge_ocr_data_into_confirmed(item)
    assert item.confirmed_data["dni_number"] == "55556666"


def test_confirmed_dni_number_updates_missionary(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = sessions()
    missionary = Missionary(
        full_name="Peruvian Example",
        missionary_code="8123",
        tracking_profile="PERUVIAN_DNI",
        current_stage="DNI",
    )
    session.add(missionary)
    session.commit()
    missionary_id = missionary.id
    session.close()

    monkeypatch.setattr(upload_pipeline, "SessionLocal", sessions)
    monkeypatch.setattr(
        upload_pipeline.MissionLegalApiClient,
        "from_environment",
        lambda: None,
    )

    updated = upload_pipeline.apply_missionary_updates(
        missionary_id,
        "DNI",
        44,
        {"dni_number": "1234 5678"},
    )

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert updated == ["dni_number"]
    assert missionary.dni_number == "12345678"
    assert json.loads(missionary.field_sources)["dni_number"] == {
        "document_id": 44,
        "document_type": "DNI",
        "label": "DNI Copy",
    }
    session.close()
