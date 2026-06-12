import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from services.document_parser import DocumentParser
from services import upload_pipeline


DOCUMENT_TYPE = "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA"


def _sample_layout_pages():
    return [
        {
            "page": 1,
            "source": "pdf_words",
            "words": [
                {
                    "text": "Usuario:",
                    "x0": 59.0,
                    "y0": 122.7,
                    "x1": 96.2,
                    "y1": 136.5,
                },
                {
                    "text": "YJ9KKRVY",
                    "x0": 150.0,
                    "y0": 122.7,
                    "x1": 201.1,
                    "y1": 136.5,
                },
                {
                    "text": "Contraseña:",
                    "x0": 59.0,
                    "y0": 142.7,
                    "x1": 113.5,
                    "y1": 156.5,
                },
                {
                    "text": "476781",
                    "x0": 150.0,
                    "y0": 142.7,
                    "x1": 183.4,
                    "y1": 156.5,
                },
            ],
        }
    ]


def test_constancia_tramite_parser_uses_same_row_layout_values():
    parsed = DocumentParser().parse(
        "",
        DOCUMENT_TYPE,
        layout_pages=_sample_layout_pages(),
    )

    assert parsed == {
        "tramite_usuario": "YJ9KKRVY",
        "tramite_contrasena": "476781",
    }


def test_constancia_tramite_layout_overrides_misleading_text_order():
    text = """
    Usuario:
    En ese sentido, se le brinda sus credenciales de ingreso:
    476781
    Enlace de
    YJ9KKRVY
    Contraseña:
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=_sample_layout_pages(),
    )

    assert parsed["tramite_usuario"] == "YJ9KKRVY"
    assert parsed["tramite_contrasena"] == "476781"


def test_constancia_tramite_parser_ignores_prose_credentials_words():
    text = """
    Asimismo, declaro bajo juramento recibir un usuario y contraseña,
    de uso personal e intransferible.
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=_sample_layout_pages(),
    )

    assert parsed["tramite_usuario"] == "YJ9KKRVY"
    assert parsed["tramite_contrasena"] == "476781"


def test_constancia_tramite_parser_does_not_duplicate_visible_value():
    layout_pages = _sample_layout_pages()
    layout_pages[0]["words"].insert(
        3,
        {
            "text": "YJ9KKRVY",
            "x0": 115.0,
            "y0": 142.7,
            "x1": 146.0,
            "y1": 156.5,
        },
    )

    parsed = DocumentParser().parse(
        "",
        DOCUMENT_TYPE,
        layout_pages=layout_pages,
    )

    assert parsed["tramite_usuario"] == "YJ9KKRVY"
    assert parsed["tramite_contrasena"] == "476781"


def test_run_ocr_on_images_passes_layout_pages_to_parser(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_ocr_texts",
        lambda image_paths, parent=None: [
            {
                "page": 0,
                "image_path": str(image_paths[0]),
                "text": "Usuario:\n476781\nYJ9KKRVY\nContraseña:",
                "lines": [],
            }
        ],
    )

    result = upload_pipeline.run_ocr_on_images(
        image_paths=["dummy.png"],
        document_type=DOCUMENT_TYPE,
        layout_pages=_sample_layout_pages(),
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "tramite_usuario": "YJ9KKRVY",
        "tramite_contrasena": "476781",
    }


def test_run_ocr_on_images_uses_layout_when_ocr_text_fails(monkeypatch):
    def fail_ocr(image_paths, parent=None):
        raise RuntimeError("OCR unavailable")

    monkeypatch.setattr(upload_pipeline, "extract_ocr_texts", fail_ocr)

    result = upload_pipeline.run_ocr_on_images(
        image_paths=["dummy.png"],
        document_type=DOCUMENT_TYPE,
        layout_pages=_sample_layout_pages(),
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "tramite_usuario": "YJ9KKRVY",
        "tramite_contrasena": "476781",
    }


def test_tramite_credentials_auto_update_missionary(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(upload_pipeline, "SessionLocal", TestingSession)

    session = TestingSession()
    missionary = Missionary(full_name="Test Missionary")
    session.add(missionary)
    session.commit()
    missionary_id = missionary.id
    session.close()

    updated = upload_pipeline.apply_missionary_updates(
        missionary_id,
        DOCUMENT_TYPE,
        99,
        {
            "tramite_usuario": "YJ9KKRVY",
            "tramite_contrasena": "476781",
        },
    )

    session = TestingSession()
    refreshed = session.query(Missionary).filter_by(id=missionary_id).one()
    sources = json.loads(refreshed.field_sources)
    session.close()

    assert set(updated) == {"tramite_usuario", "tramite_contrasena"}
    assert refreshed.tramite_usuario == "YJ9KKRVY"
    assert refreshed.tramite_contrasena == "476781"
    assert sources["tramite_usuario"]["document_id"] == 99
    assert sources["tramite_contrasena"]["document_type"] == DOCUMENT_TYPE
