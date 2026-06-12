from datetime import date

from services.document_parser import DocumentParser
from services import upload_pipeline


DOCUMENT_TYPE = "TAM"


def _tam_layout_pages():
    return [
        {
            "page": 0,
            "source": "pdf_words",
            "words": [
                {
                    "text": "FECHA",
                    "x0": 58.0,
                    "y0": 128.0,
                    "x1": 100.0,
                    "y1": 142.0,
                },
                {
                    "text": "DE",
                    "x0": 103.0,
                    "y0": 128.0,
                    "x1": 118.0,
                    "y1": 142.0,
                },
                {
                    "text": "INGRESO",
                    "x0": 121.0,
                    "y0": 128.0,
                    "x1": 184.0,
                    "y1": 142.0,
                },
                {
                    "text": "20/05/2026",
                    "x0": 58.0,
                    "y0": 147.0,
                    "x1": 120.0,
                    "y1": 161.0,
                },
            ],
        }
    ]


def test_tam_layout_uses_fecha_de_ingreso_not_text_order():
    parsed = DocumentParser().parse(
        """
        05/01/2026
        FECHA DE INGRESO
        20/05/2026
        """,
        DOCUMENT_TYPE,
        layout_pages=_tam_layout_pages(),
    )

    assert parsed == {
        "arrival_date": date(2026, 5, 20),
    }


def test_tam_prepare_uses_layout_without_ocr(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_pdf_layout_pages",
        lambda file_path, export_settings=None: _tam_layout_pages(),
    )

    def fail_export(*args, **kwargs):
        raise AssertionError("Image export should not run for TAM layout")

    monkeypatch.setattr(upload_pipeline, "export_pages_for_ocr", fail_export)

    result = upload_pipeline.prepare_ocr_ingestion(
        source_file="tam.pdf",
        document_type=DOCUMENT_TYPE,
        export_settings={"pages": "all"},
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "arrival_date": "2026-05-20",
    }
