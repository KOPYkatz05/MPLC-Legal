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


def _interpol_ocr_line_pages(include_cita_date=True):
    lines = [
        {
            "text": "FECHA NACIMIENTO",
            "x0": 448.0,
            "y0": 788.0,
            "x1": 989.0,
            "y1": 857.0,
        },
        {
            "text": "22/04/2007",
            "x0": 582.0,
            "y0": 885.0,
            "x1": 855.0,
            "y1": 949.0,
        },
        {
            "text": "FECHA CITA",
            "x0": 549.0,
            "y0": 1081.0,
            "x1": 888.0,
            "y1": 1156.0,
        },
        {
            "text": "HORA CITA",
            "x0": 1556.0,
            "y0": 1076.0,
            "x1": 1862.0,
            "y1": 1151.0,
        },
        {
            "text": "CALIDAD MIGRATORIA",
            "x0": 2384.0,
            "y0": 1081.0,
            "x1": 2980.0,
            "y1": 1151.0,
        },
        {
            "text": "11:59:59.996",
            "x0": 1552.0,
            "y0": 1182.0,
            "x1": 1885.0,
            "y1": 1260.0,
        },
        {
            "text": "Horas",
            "x0": 2013.0,
            "y0": 1186.0,
            "x1": 2200.0,
            "y1": 1262.0,
        },
        {
            "text": "FECHA DE PAGO",
            "x0": 2476.0,
            "y0": 1356.0,
            "x1": 2934.0,
            "y1": 1426.0,
        },
        {
            "text": "29/04/2026",
            "x0": 2535.0,
            "y0": 1452.0,
            "x1": 2823.0,
            "y1": 1522.0,
        },
    ]
    if include_cita_date:
        lines.insert(
            6,
            {
                "text": "20/05/2026",
                "x0": 582.0,
                "y0": 1192.0,
                "x1": 859.0,
                "y1": 1256.0,
            },
        )
    return [
        {
            "page": 0,
            "image_path": "interpol.png",
            "text": "\n".join(line["text"] for line in lines),
            "lines": lines,
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


def test_interpol_cita_ocr_line_layout_uses_fecha_cita_column():
    text = """
    FECHA NACIMIENTO
    22/04/2007
    FECHA CITA
    HORA CITA
    CALIDAD MIGRATORIA
    11:59:59.996
    20/05/2026
    Horas
    FECHA DE PAGO
    29/04/2026
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=_interpol_ocr_line_pages(),
    )

    assert parsed["interpol_appointment_date"] == date(2026, 5, 20)


def test_interpol_cita_ocr_line_layout_does_not_fill_birth_date_on_miss():
    text = """
    FECHA NACIMIENTO
    22/04/2007
    FECHA CITA
    HORA CITA
    FECHA DE PAGO
    29/04/2026
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=_interpol_ocr_line_pages(include_cita_date=False),
    )

    assert "interpol_appointment_date" not in parsed


def test_interpol_cita_plain_text_fallback_still_uses_existing_behavior():
    text = """
    FECHA NACIMIENTO
    22/04/2007
    FECHA CITA
    20/05/2026
    """

    parsed = DocumentParser().parse(
        text,
        DOCUMENT_TYPE,
        layout_pages=None,
    )

    assert parsed["interpol_appointment_date"] == date(2007, 4, 22)


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


def test_interpol_cita_run_ocr_on_images_uses_ocr_line_layout(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_ocr_texts",
        lambda image_paths, parent=None: _interpol_ocr_line_pages(),
    )

    result = upload_pipeline.run_ocr_on_images(
        image_paths=["interpol.png"],
        document_type=DOCUMENT_TYPE,
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "interpol_appointment_date": "2026-05-20",
    }
