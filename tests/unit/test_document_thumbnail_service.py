from pathlib import Path

import fitz
from PIL import Image

from services.document_thumbnail_service import DocumentThumbnailService


def test_pdf_thumbnail_is_cached_and_small(tmp_path):
    source = tmp_path / "source.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((80, 100), "Mission Legal")
    pdf.save(source)
    pdf.close()

    document = type(
        "Document",
        (),
        {"id": 4, "missionary_id": 9, "file_path": str(source)},
    )()
    service = DocumentThumbnailService(tmp_path / "thumbs")

    thumbnail = service.get_thumbnail(document)

    assert thumbnail is not None
    assert Image.open(thumbnail).size[0] <= 120
    assert Image.open(thumbnail).size[1] <= 160
    assert service.get_thumbnail(document) == thumbnail


def test_missing_thumbnail_source_returns_none(tmp_path):
    document = type(
        "Document",
        (),
        {"id": 4, "missionary_id": 9, "file_path": str(tmp_path / "missing.pdf")},
    )()

    assert DocumentThumbnailService(tmp_path / "thumbs").get_thumbnail(document) is None
