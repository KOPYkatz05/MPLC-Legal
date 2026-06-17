from datetime import date

from services.document_parser import DocumentParser
from services import upload_pipeline


def _word(text, x0, y0, x1=None, y1=None):
    return {
        "text": text,
        "x0": x0,
        "y0": y0,
        "x1": x1 if x1 is not None else x0 + max(len(text) * 6, 4),
        "y1": y1 if y1 is not None else y0 + 13,
    }


def _layout_pages(words):
    return [
        {
            "page": 0,
            "source": "pdf_words",
            "words": words,
        }
    ]


def _recojo_layout_pages():
    return _layout_pages([
        _word("FECHA", 20, 178),
        _word("DE", 57, 178),
        _word("NACIMIENTO", 73, 178),
        _word(":", 177, 178),
        _word("22/10/2005", 200, 178),
        _word("PROGRAMACION", 20, 207),
        _word("DE", 123, 207),
        _word("CITA", 143, 207),
        _word("FECHA", 20, 298),
        _word("DE", 57, 298),
        _word("CITA", 73, 298),
        _word(":", 176, 298),
        _word("12/10/2024", 199, 298),
        _word("HORARIO", 20, 318),
        _word("DE", 69, 318),
        _word("CITA", 86, 318),
        _word(":", 176, 318),
        _word("08:00", 199, 318),
    ])


def _biometric_layout_pages():
    return _layout_pages([
        _word("FECHA", 20, 183),
        _word("DE", 53, 183),
        _word("NACIMIENTO", 68, 183),
        _word("11/04/2006", 200, 183),
        _word("PROGRAMACION", 20, 263),
        _word("DE", 106, 263),
        _word("CITA", 123, 263),
        _word("TIPO", 20, 283),
        _word("DE", 44, 283),
        _word("TRAMITE", 59, 283),
        _word(":", 176, 283),
        _word("REGISTRO", 199, 283),
        _word("DATOS", 249, 283),
        _word("BIOMETRICOS", 282, 283),
        _word("FECHA", 20, 344),
        _word("DE", 53, 344),
        _word("CITA", 68, 344),
        _word(":", 176, 344),
        _word("31/10/2025", 199, 344),
        _word("HORARIO", 20, 362),
        _word("DE", 65, 362),
        _word("CITA", 80, 362),
        _word(":", 176, 362),
        _word("11:00", 199, 362),
    ])


def _prorroga_layout_pages():
    return _layout_pages([
        _word("Expediente", 84, 262),
        _word("Fecha", 172, 262),
        _word("04/08/2025", 251, 289),
        _word("Fecha:", 60, 407),
        _word("Lima,", 87, 407),
        _word("04", 111, 407),
        _word("de", 123, 407),
        _word("Agosto", 135, 407),
        _word("de", 166, 407),
        _word("2025", 179, 407),
        _word("La", 60, 775),
        _word("fecha", 75, 775),
        _word("de", 107, 775),
        _word("vencimiento", 123, 775),
        _word("de", 191, 775),
        _word("su", 208, 775),
        _word("residencia", 223, 775),
        _word("es:", 280, 775),
        _word("11/09/2026", 297, 775),
    ])


def test_recojo_layout_uses_fecha_cita_not_birth_date():
    parsed = DocumentParser().parse(
        "",
        "CITA_RECOJO",
        layout_pages=_recojo_layout_pages(),
    )

    assert parsed == {
        "pickup_appointment_date": date(2024, 10, 12),
    }


def test_biometric_layout_uses_fecha_cita_not_birth_date():
    parsed = DocumentParser().parse(
        "",
        "CONSTANCIA_DE_CITA_BIOMETRICO",
        layout_pages=_biometric_layout_pages(),
    )

    assert parsed == {
        "biometric_appointment_date": date(2025, 10, 31),
    }


def test_prorroga_layout_uses_residency_expiration_not_prior_dates():
    parsed = DocumentParser().parse(
        "",
        "APROBACION_DE_PRORROGA",
        layout_pages=_prorroga_layout_pages(),
    )

    assert parsed == {
        "prorroga_expiration": date(2026, 9, 11),
    }


def test_recojo_prepare_uses_layout_without_ocr(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_pdf_layout_pages",
        lambda file_path, export_settings=None: _recojo_layout_pages(),
    )

    def fail_export(*args, **kwargs):
        raise AssertionError("Image export should not run for recojo layout")

    monkeypatch.setattr(upload_pipeline, "export_pages_for_ocr", fail_export)

    result = upload_pipeline.prepare_ocr_ingestion(
        source_file="recojo.pdf",
        document_type="CITA_RECOJO",
        export_settings={"pages": "all"},
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "pickup_appointment_date": "2024-10-12",
    }


def test_biometric_prepare_uses_layout_without_ocr(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_pdf_layout_pages",
        lambda file_path, export_settings=None: _biometric_layout_pages(),
    )

    def fail_export(*args, **kwargs):
        raise AssertionError("Image export should not run for biometric layout")

    monkeypatch.setattr(upload_pipeline, "export_pages_for_ocr", fail_export)

    result = upload_pipeline.prepare_ocr_ingestion(
        source_file="biometric.pdf",
        document_type="CONSTANCIA_DE_CITA_BIOMETRICO",
        export_settings={"pages": "all"},
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "biometric_appointment_date": "2025-10-31",
    }


def test_prorroga_prepare_uses_layout_without_ocr(monkeypatch):
    monkeypatch.setattr(
        upload_pipeline,
        "extract_pdf_layout_pages",
        lambda file_path, export_settings=None: _prorroga_layout_pages(),
    )

    def fail_export(*args, **kwargs):
        raise AssertionError("Image export should not run for prorroga layout")

    monkeypatch.setattr(upload_pipeline, "export_pages_for_ocr", fail_export)

    result = upload_pipeline.prepare_ocr_ingestion(
        source_file="prorroga.pdf",
        document_type="APROBACION_DE_PRORROGA",
        export_settings={"pages": "all"},
    )

    assert result.ocr_status == "success"
    assert result.parsed_data == {
        "prorroga_expiration": "2026-09-11",
    }
