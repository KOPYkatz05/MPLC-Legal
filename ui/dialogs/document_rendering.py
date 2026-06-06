from pathlib import Path

import fitz

from PySide6.QtGui import QImage, QPainter, QPixmap


DEFAULT_RENDER_SCALE = 3.0

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}


def get_document_viewer_render_hints():
    return QPainter.Antialiasing | QPainter.SmoothPixmapTransform


def get_pdf_page_count(file_path):
    path = Path(file_path)
    if not path.exists() or path.suffix.lower() != ".pdf":
        return 0

    doc = fitz.open(str(path))
    try:
        return doc.page_count
    finally:
        doc.close()


def render_pdf_page(document, page_index=0, render_scale=DEFAULT_RENDER_SCALE):
    if document is None or getattr(document, "page_count", 0) <= 0:
        return None

    page_index = max(0, min(page_index, document.page_count - 1))
    page = document.load_page(page_index)
    pix = page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale),
        alpha=False,
    )
    image = QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format_RGB888,
    )
    return QPixmap.fromImage(image.copy())


def render_document_pixmap(file_path, page_index=0, render_scale=DEFAULT_RENDER_SCALE):
    path = Path(file_path)
    if not path.exists():
        return None

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(str(path))
        try:
            return render_pdf_page(doc, page_index, render_scale)
        finally:
            doc.close()

    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return QPixmap(str(path))

    return None
