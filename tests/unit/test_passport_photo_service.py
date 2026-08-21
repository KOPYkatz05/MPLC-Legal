from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from services.passport_photo_service import (
    PassportPhotoCandidate,
    PassportPhotoService,
)
from ui.dialogs.upload_session.controller import UploadSessionController
from ui.dialogs.upload_session.models import UploadQueueItem
from ui.dialogs.passport_photo_review_dialog import PassportPhotoReviewDialog


class _FaceCascade:
    def empty(self):
        return False

    def detectMultiScale(self, image, **_kwargs):
        height, width = image.shape[:2]
        return np.array([[width // 3, height // 4, width // 5, width // 5]])


class _Missionary:
    id = 17


def test_detects_and_crops_a_color_portrait():
    source = Image.new("RGB", (1000, 700), (40, 120, 210))
    service = PassportPhotoService.__new__(PassportPhotoService)
    service._cascade = _FaceCascade()

    candidate = service._best_crop(source, page_index=2)

    assert candidate is not None
    score, page_index, portrait = candidate
    assert score > 0
    assert page_index == 2
    assert portrait.mode == "RGB"
    assert portrait.width > 80
    assert portrait.height > 100


def test_review_candidate_keeps_the_complete_passport_page():
    full_page = Image.new("RGB", (1000, 700), (40, 120, 210))
    service = PassportPhotoService.__new__(PassportPhotoService)
    service._cascade = _FaceCascade()
    service._source_images = lambda _path: iter([(0, full_page)])

    candidate = service.extract("passport.pdf")

    assert candidate is not None
    with Image.open(candidate.path) as review_image:
        assert review_image.size == (1000, 700)
        assert review_image.size != PassportPhotoReviewDialog.OUTPUT_SIZE
    candidate.path.unlink()


def test_controller_queues_one_reviewable_photo_per_passport():
    controller = UploadSessionController.__new__(UploadSessionController)
    controller.missionary = _Missionary()
    controller.items = []
    passport = UploadQueueItem(
        file_path="passport.pdf",
        document_type="PASSPORT",
    )
    controller.items.append(passport)
    candidate = PassportPhotoCandidate(
        Path("derived.jpg"), page_index=1, score=0.9
    )

    queued = controller.add_passport_photo_candidate(passport, candidate)

    assert queued.document_type == "PHOTO"
    assert queued.status == "review"
    assert queued.derived_photo_approved is False
    assert queued.derived_from_upload_id == passport.upload_id
    assert "page 2" in queued.notes
    assert controller.add_passport_photo_candidate(passport, candidate) is None
    assert len(controller.items) == 2

    result = controller.save_item(queued)
    assert result.status == "failed"
    assert "Approve or reject" in result.error_text


def test_review_dialog_has_explicit_approve_and_reject_controls(qtbot):
    preview_path = (
        Path.cwd()
        / "assets"
        / "icons"
        / "mission_legal"
        / "mission_legal_icon.png"
    )
    dialog = PassportPhotoReviewDialog(preview_path)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Approve Missionary Photo"
    assert dialog.approve_button.text() == "Approve Photo"
    assert dialog.reject_button.text() == "Cancel"
    assert dialog.approve_button.isDefault()
    assert dialog.reset_crop_button.text() == "Reset Crop"
    assert dialog.zoom_in_button.text() == "Zoom In"
    assert dialog.zoom_out_button.text() == "Zoom Out"
    assert dialog.fit_view_button.text() == "Fit"
    pixmap_item = dialog.pixmap_item
    crop_item = dialog.graphics_view.crop_item
    dialog.rotation_ruler.set_angle(721.5)
    qtbot.wait(20)
    assert dialog.rotation_angle == 721.5
    assert dialog.rotation_ruler.angle == 721.5
    assert dialog.rotation_ruler.normalized_angle(721.5) == 1.5
    assert dialog.pixmap_item is pixmap_item
    assert dialog.graphics_view.crop_item is crop_item

    dialog.graphics_view.fit_scene()
    fitted_scale = dialog.graphics_view.transform().m11()
    dialog.graphics_view.zoom_by(1.25)
    assert dialog.graphics_view.transform().m11() > fitted_scale
    dialog.graphics_view.fit_scene()
    assert abs(dialog.graphics_view.transform().m11() - fitted_scale) < 0.001

    assert dialog.graphics_view.get_crop_rect() is None
    assert dialog.approve_button.isEnabled() is False
    assert dialog.graphics_view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.graphics_view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.rotation_ruler.parent() is dialog.graphics_view


def test_review_dialog_handles_parent_events_during_construction(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()

    dialog = PassportPhotoReviewDialog(Path("missing-preview.jpg"), host)
    qtbot.addWidget(dialog)

    host.resize(900, 700)
    dialog.show()
    qtbot.wait(50)
    assert dialog.graphics_view is not None
    assert dialog.rotation_ruler.parent() is dialog.graphics_view


def test_empty_review_dialog_can_select_a_photo_without_touching_source(
    qtbot, monkeypatch
):
    source = (
        Path.cwd()
        / "assets"
        / "icons"
        / "mission_legal"
        / "mission_legal_icon.png"
    )
    original_bytes = source.read_bytes()
    monkeypatch.setattr(
        "ui.dialogs.passport_photo_review_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "Images"),
    )
    dialog = PassportPhotoReviewDialog()
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Add Missionary Photo"
    assert dialog.empty_message.text() == "No photo found, select a photo to start."
    assert not dialog.choose_photo_button.icon().isNull()
    assert dialog.photo_path is None

    dialog.choose_photo_button.click()

    assert dialog.photo_path is not None
    assert dialog.photo_path != source
    assert dialog.photo_path.exists()
    assert dialog.empty_state.isHidden()
    assert dialog.graphics_view.get_crop_rect() is None
    assert source.read_bytes() == original_bytes
    temporary_path = dialog.photo_path
    dialog.reject()
    assert not temporary_path.exists()


def test_empty_review_dialog_accepts_a_passport_pdf_for_photo_only(
    qtbot, monkeypatch
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as handle:
        rendered_path = Path(handle.name)
    Image.new("RGB", (800, 1100), "white").save(rendered_path, "JPEG")
    picker_filters = []

    def choose_pdf(*args, **_kwargs):
        picker_filters.append(args[-1])
        return ("passport.pdf", args[-1])

    monkeypatch.setattr(
        "ui.dialogs.passport_photo_review_dialog.QFileDialog.getOpenFileName",
        choose_pdf,
    )
    monkeypatch.setattr(
        "ui.dialogs.passport_photo_review_dialog.PassportPhotoService.extract",
        lambda _self, path: SimpleNamespace(path=rendered_path),
    )
    dialog = PassportPhotoReviewDialog()
    qtbot.addWidget(dialog)

    dialog.choose_photo_button.click()

    assert "*.pdf" in picker_filters[0]
    assert dialog.photo_path == rendered_path
    assert not dialog.original_pixmap.isNull()
    assert dialog.graphics_view.get_crop_rect() is None
    dialog.reject()
    assert not rendered_path.exists()
