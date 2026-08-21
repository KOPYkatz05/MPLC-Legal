from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import shutil

import fitz

from services.document_service import DocumentFileUnavailableError
from services.print_packet_registry import get_packet_definition
from services.printing_models import PrintOutputMode, PrintStatus
from services.printing_service import PrintingService


def _pdf(path, text):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class FakeDocumentService:
    api_client = None

    def __init__(self, documents, unavailable=()):
        self.documents = documents
        self.unavailable = set(unavailable)
        self.resolved = []

    def get_documents(self, missionary_id):
        return list(self.documents)

    def ensure_local_copy(self, document):
        self.resolved.append(document.id)
        if document.id in self.unavailable:
            raise DocumentFileUnavailableError(document.id)
        return Path(document.file_path)


@pytest.fixture
def print_tmp_path():
    path = Path.cwd() / "run_tmp" / f"printing-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_interpol_registry_conditionally_includes_fbi():
    definition = get_packet_definition("interpol")
    peru = SimpleNamespace(nationality="Peru")
    usa = SimpleNamespace(nationality="United States")

    assert "FBI" not in [
        rule.document_type for rule in definition.documents if rule.applies_to(peru)
    ]
    assert "FBI" in [
        rule.document_type for rule in definition.documents if rule.applies_to(usa)
    ]


def test_prepare_packet_resolves_newest_and_classifies_gaps(print_tmp_path, monkeypatch):
    tam = print_tmp_path / "tam.pdf"
    passport = print_tmp_path / "passport.pdf"
    _pdf(tam, "TAM")
    _pdf(passport, "PASSPORT")
    now = datetime.now()
    records = [
        SimpleNamespace(id=1, missionary_id=7, document_type="TAM", status="ACTIVE", uploaded_at=now, file_path=str(tam)),
        SimpleNamespace(id=2, missionary_id=7, document_type="PASSPORT", status="ACTIVE", uploaded_at=now - timedelta(days=1), file_path=str(passport)),
        SimpleNamespace(id=3, missionary_id=7, document_type="PASSPORT", status="ACTIVE", uploaded_at=now, file_path=str(passport)),
        SimpleNamespace(id=4, missionary_id=7, document_type="PAGO_INTERPOL", status="ACTIVE", uploaded_at=now, file_path="remote.pdf"),
    ]
    document_service = FakeDocumentService(records, unavailable={4})
    monkeypatch.setattr(
        "services.printing_service.interpol_annotation_lines",
        lambda missionary, service: ["complete"],
    )
    service = PrintingService(document_service, temp_root=print_tmp_path)
    missionary = SimpleNamespace(id=7, full_name="Elder Test", nationality="Peru")

    job = service.prepare_packet("INTERPOL", missionary)

    assert [document.record.id for document in job.documents] == [1, 3]
    assert document_service.resolved == [1, 3, 4]
    assert job.unavailable_documents == [service.document_label("PAGO_INTERPOL")]
    assert job.missing_documents == [
        service.document_label("CONSTANCIA_DE_CITA_INTERPOL")
    ]


def test_build_pdf_preserves_order_and_replaces_atomically(print_tmp_path):
    first = print_tmp_path / "first.pdf"
    second = print_tmp_path / "second.png"
    _pdf(first, "FIRST")
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pixmap.clear_with(255)
    pixmap.save(second)
    records = [
        SimpleNamespace(id=1, missionary_id=7, document_type="TAM", status="ACTIVE", uploaded_at=None, file_path=str(first)),
        SimpleNamespace(id=2, missionary_id=7, document_type="PAGO_INTERPOL", status="ACTIVE", uploaded_at=None, file_path=str(second)),
    ]
    service = PrintingService(FakeDocumentService(records), temp_root=print_tmp_path)
    job = service.prepare_packet(
        "INTERPOL",
        SimpleNamespace(id=7, full_name="Test", nationality="Peru"),
    )
    output = print_tmp_path / "packet.pdf"

    service.build_pdf(job, output)

    with fitz.open(output) as packet:
        assert packet.page_count == 2
        assert "FIRST" in packet[0].get_text()
    assert not output.with_suffix(".pdf.partial").exists()


def test_finish_job_returns_completed_and_delivers(print_tmp_path, monkeypatch):
    source = print_tmp_path / "source.pdf"
    _pdf(source, "READY")
    record = SimpleNamespace(id=1, missionary_id=7, document_type="TAM", status="ACTIVE", uploaded_at=None, file_path=str(source))
    service = PrintingService(FakeDocumentService([record]), temp_root=print_tmp_path)
    job = service.prepare_packet(
        "INTERPOL",
        SimpleNamespace(id=7, full_name="Test", nationality="Peru"),
    )
    delivered = []
    monkeypatch.setattr(
        service,
        "deliver",
        lambda path, mode: delivered.append((path, mode)),
    )

    result = service.finish_job(job, PrintOutputMode.OPEN_PREVIEW)

    assert result.status == PrintStatus.COMPLETED
    assert result.output_path.is_file()
    assert delivered == [(result.output_path, PrintOutputMode.OPEN_PREVIEW)]
