import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from services.document_parser import DocumentParser
from services import upload_pipeline


def test_constancia_tramite_parser_extracts_usuario_and_contrasena():
    text = """
    Constancia de Tramite Carne de Extranjeria
    Usuario: ARDILES2026
    Contrasena: TCE-84921
    """

    parsed = DocumentParser().parse(
        text,
        "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
    )

    assert parsed == {
        "tramite_usuario": "ARDILES2026",
        "tramite_contrasena": "TCE-84921",
    }


def test_constancia_tramite_parser_extracts_values_on_next_line():
    text = """
    Usuario
    ARDILES2026

    Password
    TCE-84921
    """

    parsed = DocumentParser().parse(
        text,
        "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
    )

    assert parsed["tramite_usuario"] == "ARDILES2026"
    assert parsed["tramite_contrasena"] == "TCE-84921"


def test_constancia_tramite_parser_handles_migraciones_layout():
    text = """
    Usuario:
    En ese sentido, se le brinda sus credenciales de ingreso:
    476781
    Enlace de
    YJ9KKRVY
    Contrasena:
    CREDENCIALES DE ACCESO AL BUZON ELECTRONICO
    """

    parsed = DocumentParser().parse(
        text,
        "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
    )

    assert parsed["tramite_usuario"] == "476781"
    assert parsed["tramite_contrasena"] == "YJ9KKRVY"


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
        "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
        99,
        {
            "tramite_usuario": "ARDILES2026",
            "tramite_contrasena": "TCE-84921",
        },
    )

    session = TestingSession()
    refreshed = session.query(Missionary).filter_by(id=missionary_id).one()
    sources = json.loads(refreshed.field_sources)
    session.close()

    assert set(updated) == {"tramite_usuario", "tramite_contrasena"}
    assert refreshed.tramite_usuario == "ARDILES2026"
    assert refreshed.tramite_contrasena == "TCE-84921"
    assert sources["tramite_usuario"]["document_id"] == 99
    assert (
        sources["tramite_contrasena"]["document_type"]
        == "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA"
    )
