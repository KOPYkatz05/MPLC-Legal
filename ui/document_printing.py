"""Native Qt printing for document files already resolved to local storage."""

from pathlib import Path

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from ui.dialogs.document_rendering import SUPPORTED_IMAGE_EXTENSIONS


def _fit_rect(source_size, target_rect):
    source_width = max(1, source_size.width())
    source_height = max(1, source_size.height())
    scale = min(
        target_rect.width() / source_width,
        target_rect.height() / source_height,
    )
    width = source_width * scale
    height = source_height * scale
    return QRectF(
        target_rect.x() + (target_rect.width() - width) / 2,
        target_rect.y() + (target_rect.height() - height) / 2,
        width,
        height,
    )


def _pdf_page_image(page, printer):
    dpi = max(144, min(300, printer.resolution()))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format_RGB888,
    )
    return image.copy()


def _paint_image(painter, printer, image):
    page_rect = QRectF(printer.pageRect(QPrinter.DevicePixel))
    target = _fit_rect(image.size(), page_rect)
    painter.drawImage(target, image)


def print_document_file(file_path, *, parent=None, job_name=None):
    """Show the native printer dialog and print a PDF or supported image."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix != ".pdf" and suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported printable file format: {suffix or 'unknown'}")

    printer = QPrinter(QPrinter.HighResolution)
    printer.setDocName(job_name or path.name)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.Accepted:
        return False

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("The selected printer could not start the print job.")
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if suffix == ".pdf":
            with fitz.open(str(path)) as document:
                if document.page_count <= 0:
                    raise ValueError("The PDF has no printable pages.")
                for page_index, page in enumerate(document):
                    if page_index and not printer.newPage():
                        raise RuntimeError("The printer could not start a new page.")
                    _paint_image(painter, printer, _pdf_page_image(page, printer))
        else:
            image = QImage(str(path))
            if image.isNull():
                raise ValueError("The image could not be prepared for printing.")
            _paint_image(painter, printer, image)
    finally:
        painter.end()
    return True

