from datetime import date

from services.document_parser import DocumentParser
from services import upload_pipeline


DOCUMENT_TYPE = "CONSTANCIA_DE_CITA_INTERPOL"


def _interpol_layout_pages():
    return [
        {
            "page": 0,
            "source": "pdf_words",
            "words": [
                {
                    "text": "FECHA",
                    "x0": 59.72,
                    "y0": 150.76,
                    "x1": 94.16,
                    "y1": 164.53,
                },
                {
                    "text": "NACIMIENTO",
                    "x0": 96.94,
                    "y0": 150.76,
                    "x1": 160.27,
                    "y1": 164.53,
                },
                {
                    "text": "01/03/2006",
                    "x0": 84.98,
                    "y0": 168.71,
                    "x1": 135.02,
                    "y1": 182.45,
                },
                {
                    "text": "FECHA",
                    "x0": 79.72,
                    "y0": 206.76,
                    "x1": 114.16,
                    "y1": 220.53,
                },
                {
                    "text": "CITA",
                    "x0": 116.94,
                    "y0": 206.76,
                    "x1": 140.27,
                    "y1": 220.53,
                },
                {
                    "text": "08/04/2026",
                    "x0": 84.98,
                    "y0": 226.71,
                    "x1": 135.02,
                    "y1": 240.45,
                },
                {
                    "text": "FECHA",
                    "x0": 446.94,
                    "y0": 259.76,
                    "x1": 481.38,
                    "y1": 273.53,
                },
                {
                    "text": "DE",
                    "x0": 484.0,
                    "y0": 259.76,
                    "x1": 500.0,
                    "y1": 273.53,
                },
                {
                    "text": "PAGO",
                    "x0": 503.0,
                    "y0": 259.76,
                    "x1": 540.0,
                    "y1": 273.53,
                },
                {
                    "text": "13/03/2026",
                    "x0": 452.0,
                    "y0": 278.0,
                    "x1": 505.0,
                    "y1": 292.0,
                },
            ],
        }
    ]


def test_interpol_cita_layout_uses_fecha_cita_not_birth_date():
    parsed = DocumentParser().parse(
        "",
        DOCUMENT_TYPE,
        layout_pages=_interpol_layout_pages(),
    )

    assert parsed == {
        "interpol_appointment_date": date(2026, 4, 8),
    }


def test_interpol_cita_layout_overrides_text_date_order():
    text = """
    FECHA NACIMIENTO
    01/03/2006
    FECHA CITA
    08/04/2026
    FECHA DE PAGO
    13/03/2026
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=_interpol_layout_pages(),
    )

    assert parsed["interpol_appointment_date"] == date(2026, 4, 8)


def test_interpol_cita_prepare_uses_layout_without_ocr(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_pdf_layout_pages",
        lambda file_path, export_settings=None: _interpol_layout_pages(),
    )

    def fail_export(*args, **kwargs):
        raise AssertionError("Image export should not run for layout-only parse")

    monkeypatch.setattr(upload_pipeline, "export_pages_for_ocr", fail_export)

    result = upload_pipeline.prepare_ocr_ingestion(
        source_file="interpol.pdf",
        document_type=DOCUMENT_TYPE,
        export_settings={"pages": "all"},
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "interpol_appointment_date": "2026-04-08",
    }
