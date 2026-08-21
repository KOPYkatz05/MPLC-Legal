import fitz
import pytest
import shutil
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from ui.dialogs.document_viewer_dialog import (
    PREVIEW_MAX_SCALE,
    PREVIEW_MIN_SCALE,
    DocumentPreviewWidget,
    DocumentViewerDialog,
)


@pytest.fixture
def tmp_path():
    path = Path.cwd() / "run_tmp" / f"document-viewer-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_legacy_document_preview_module_reexports_canonical_api():
    from ui.dialogs import document_preview
    from ui.dialogs import document_viewer_dialog

    assert (
        document_preview.DocumentPreviewGraphicsView
        is document_viewer_dialog.DocumentPreviewGraphicsView
    )
    assert (
        document_preview.DocumentPreviewWidget
        is document_viewer_dialog.DocumentPreviewWidget
    )
    assert (
        document_preview.DocumentViewerDialog
        is document_viewer_dialog.DocumentViewerDialog
    )
    assert document_preview.PREVIEW_MIN_SCALE == PREVIEW_MIN_SCALE
    assert document_preview.PREVIEW_MAX_SCALE == PREVIEW_MAX_SCALE


def _make_image(path):
    image = QImage(80, 120, QImage.Format_RGB32)
    image.fill(QColor("#ffffff"))
    assert image.save(str(path))
    return path


def _make_pdf(path, pages=2):
    doc = fitz.open()
    try:
        for index in range(pages):
            page = doc.new_page(width=160, height=220)
            page.insert_text((36, 72), f"Page {index + 1}")
        doc.save(str(path))
    finally:
        doc.close()
    return path


def test_image_loads_preview_without_page_controls(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")

    dialog = DocumentViewerDialog(str(image_path))
    try:
        assert dialog.header.parentWidget() is dialog.preview_widget
        assert dialog.current_pixmap is not None
        assert dialog._preview_item is not None
        assert dialog.page_combo.isHidden()
        assert dialog.preview_zoom_in_btn.isEnabled()
        assert not dialog.graphics_view.isHidden()
        assert dialog.preview_empty_label.isHidden()
        assert dialog.print_btn.isEnabled()
        assert dialog.download_btn.isEnabled()
    finally:
        dialog.close()


def test_document_preview_widget_embeds_without_dialog_shell(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")

    widget = DocumentPreviewWidget(str(image_path), show_header=False)
    try:
        assert widget.current_pixmap is not None
        assert widget._preview_item is not None
        assert widget.preview_name_label.parent().isHidden()
    finally:
        widget.close()


def test_pdf_page_navigation_updates_current_page(tmp_path, qapp):
    pdf_path = _make_pdf(tmp_path / "document.pdf", pages=2)

    dialog = DocumentViewerDialog(str(pdf_path))
    try:
        assert dialog.page_combo.count() == 2
        assert not dialog.page_combo.isHidden()
        assert dialog.page_combo.currentIndex() == 0
        assert "Page 1 of 2" in dialog.preview_meta_label.text()

        dialog.go_to_next_page()

        assert dialog.page_combo.currentIndex() == 1
        assert "Page 2 of 2" in dialog.preview_meta_label.text()

        dialog.go_to_previous_page()

        assert dialog.page_combo.currentIndex() == 0
        assert "Page 1 of 2" in dialog.preview_meta_label.text()
    finally:
        dialog.close()


def test_missing_path_shows_empty_state_and_disables_preview(tmp_path, qapp):
    dialog = DocumentViewerDialog(str(tmp_path / "missing.pdf"))
    try:
        assert dialog._preview_item is None
        assert not dialog.preview_empty_label.isHidden()
        assert "Cannot open document file" in dialog.preview_empty_label.text()
        assert dialog.graphics_view.isHidden()
        assert not dialog.preview_zoom_in_btn.isEnabled()
        assert not dialog.print_btn.isEnabled()
        assert not dialog.download_btn.isEnabled()
    finally:
        dialog.close()


def test_unsupported_path_shows_empty_state_and_disables_preview(tmp_path, qapp):
    text_path = tmp_path / "document.txt"
    text_path.write_text("not a previewable document", encoding="utf-8")

    dialog = DocumentViewerDialog(str(text_path))
    try:
        assert dialog._preview_item is None
        assert not dialog.preview_empty_label.isHidden()
        assert "Unsupported file format" in dialog.preview_empty_label.text()
        assert not dialog.preview_zoom_out_btn.isEnabled()
        assert not dialog.print_btn.isEnabled()
        assert not dialog.download_btn.isEnabled()
    finally:
        dialog.close()


def test_zoom_clamps_scale_and_updates_label(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")

    dialog = DocumentViewerDialog(str(image_path))
    try:
        dialog._preview_scale = PREVIEW_MAX_SCALE
        dialog.zoom_in_preview()

        assert dialog._preview_scale == PREVIEW_MAX_SCALE
        assert dialog.preview_zoom_label.text() == "800%"

        dialog._preview_scale = PREVIEW_MIN_SCALE
        dialog.zoom_out_preview()

        assert dialog._preview_scale == PREVIEW_MIN_SCALE
        assert dialog.preview_zoom_label.text() == "5%"
    finally:
        dialog.close()


def test_surface_minimum_is_not_old_fixed_size(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")

    dialog = DocumentViewerDialog(str(image_path))
    try:
        assert dialog.surface.minimumSize() != QSize(900, 700)
    finally:
        dialog.close()


def test_responsive_geometry_uses_parent_container_size(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")
    parent = QWidget()
    parent.resize(1400, 900)

    dialog = DocumentViewerDialog(str(image_path), parent=parent)
    try:
        dialog._apply_responsive_shell_geometry()

        screen = dialog._responsive_screen()
        available = screen.availableGeometry()
        container_width = min(available.width(), parent.width())
        container_height = min(available.height(), parent.height())
        target_width = min(
            max(900, int(container_width * 0.82)),
            max(1, container_width - 96),
        )
        target_height = min(
            max(640, int(container_height * 0.84)),
            max(1, container_height - 48),
        )

        assert dialog.size() == parent.size()
        assert dialog.surface.size() == QSize(target_width, target_height)
    finally:
        dialog.close()
        parent.close()


def test_resize_preserves_fit_zoom_mode(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")

    dialog = DocumentViewerDialog(str(image_path))
    try:
        dialog.fit_preview_width()
        assert dialog._preview_zoom_mode == "fit_width"

        dialog.resize(900, 700)
        qapp.processEvents()

        assert dialog._preview_zoom_mode == "fit_width"
        assert dialog.preview_zoom_label.text().startswith("Fit W")
    finally:
        dialog.close()


def test_surface_clips_viewer_children_at_rounded_corners(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")
    parent = QWidget()
    parent.resize(1200, 800)
    parent.show()
    dialog = DocumentViewerDialog(str(image_path), parent=parent)
    try:
        dialog.show()
        qapp.processEvents()

        rendered = dialog.surface.grab().toImage()
        corner = rendered.pixelColor(QPoint(0, 0))
        interior_point = dialog.header.mapTo(dialog.surface, QPoint(30, 30))
        interior = rendered.pixelColor(interior_point)

        assert corner != interior
        assert interior.lightness() > corner.lightness()
        corner_alphas = {
            rendered.pixelColor(x, y).alpha()
            for x in range(21)
            for y in range(21)
        }
        assert 0 in corner_alphas
        assert 255 in corner_alphas
        assert any(0 < alpha < 255 for alpha in corner_alphas)
    finally:
        dialog.close()
        parent.close()


def test_viewer_content_is_flat_and_toolbar_is_compact(tmp_path, qapp):
    image_path = _make_image(tmp_path / "document.png")
    dialog = DocumentViewerDialog(str(image_path))
    try:
        assert dialog.preview_card.objectName() == "DocumentViewerContent"
        assert dialog.preview_card.layout().contentsMargins().left() == 0
        assert dialog.preview_card.layout().spacing() == 0
        assert dialog.preview_toolbar.objectName() == "DocumentViewerToolbar"
        assert dialog.preview_toolbar.height() == 40
        assert dialog.preview_toolbar.layout().contentsMargins().top() == 5
        assert dialog.preview_toolbar.layout().itemAt(
            dialog.preview_toolbar.layout().count() - 1
        ).spacerItem() is not None
        assert dialog.graphics_view.objectName() == "DocumentViewerCanvas"
    finally:
        dialog.close()


def test_print_button_prints_current_local_document(tmp_path, qapp, monkeypatch):
    image_path = _make_image(tmp_path / "document.png")
    calls = []
    monkeypatch.setattr(
        "ui.dialogs.document_viewer_dialog.print_document_file",
        lambda file_path, **kwargs: calls.append((file_path, kwargs)) or True,
    )
    dialog = DocumentViewerDialog(str(image_path))
    try:
        dialog.print_btn.click()

        assert len(calls) == 1
        assert calls[0][0] == image_path
        assert calls[0][1]["parent"] is dialog.preview_widget.window()
        assert calls[0][1]["job_name"] == image_path.name
    finally:
        dialog.close()


def test_download_button_saves_current_cached_document(tmp_path, qapp, monkeypatch):
    image_path = _make_image(tmp_path / "document.png")
    destination = tmp_path / "saved-copy.png"
    messages = []
    monkeypatch.setattr(
        "ui.dialogs.document_viewer_dialog.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )
    monkeypatch.setattr(
        "ui.dialogs.document_viewer_dialog.show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = DocumentViewerDialog(str(image_path))
    try:
        dialog.download_btn.click()

        assert destination.read_bytes() == image_path.read_bytes()
        assert messages[-1][1]["kind"] == "information"
        assert not destination.with_suffix(".png.partial").exists()
    finally:
        dialog.close()
