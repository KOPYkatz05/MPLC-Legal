import shutil
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import QWidget

from ui.dialogs.upload_session_dialog import (
    UploadSessionDialog,
    supported_upload_files_from_paths,
)
from ui.pages import missionary_detail_page as detail_module


def _build_upload_dialog(qapp):
    parent = QWidget()
    parent.resize(1200, 800)
    missionary = SimpleNamespace(id=42, full_name="Test Missionary")
    dialog = UploadSessionDialog(missionary, parent=parent)
    return dialog, parent


def _quiet_after_save_ui(dialog, monkeypatch):
    monkeypatch.setattr(dialog, "refresh_queue", lambda: None)
    monkeypatch.setattr(dialog, "clear_detail", lambda: None)
    monkeypatch.setattr(dialog, "update_progress", lambda: None)
    monkeypatch.setattr(dialog, "_update_action_states", lambda: None)


def test_after_save_emits_for_appointment_updated_fields(monkeypatch, qapp):
    dialog, parent = _build_upload_dialog(qapp)
    _quiet_after_save_ui(dialog, monkeypatch)
    emitted = []
    dialog.appointment_dates_updated.connect(
        lambda missionary_id, fields: emitted.append(
            (missionary_id, list(fields))
        )
    )

    try:
        dialog.controller.updated_fields = [
            "arrival_date",
            "interpol_appointment_date",
        ]

        dialog.after_save()

        assert emitted == [
            (42, ["interpol_appointment_date"])
        ]
    finally:
        dialog.close()
        parent.close()


def test_after_save_ignores_non_appointment_updated_fields(monkeypatch, qapp):
    dialog, parent = _build_upload_dialog(qapp)
    _quiet_after_save_ui(dialog, monkeypatch)
    emitted = []
    dialog.appointment_dates_updated.connect(
        lambda missionary_id, fields: emitted.append(
            (missionary_id, list(fields))
        )
    )

    try:
        dialog.controller.updated_fields = [
            "arrival_date",
            "passport_expiration",
        ]

        dialog.after_save()

        assert emitted == []
    finally:
        dialog.close()
        parent.close()


def test_after_save_does_not_emit_duplicate_appointment_fields(
    monkeypatch,
    qapp,
):
    dialog, parent = _build_upload_dialog(qapp)
    _quiet_after_save_ui(dialog, monkeypatch)
    emitted = []
    dialog.appointment_dates_updated.connect(
        lambda missionary_id, fields: emitted.append(
            (missionary_id, list(fields))
        )
    )

    try:
        dialog.controller.updated_fields = [
            "biometric_appointment_date",
        ]

        dialog.after_save()
        dialog.after_save()

        assert emitted == [
            (42, ["biometric_appointment_date"])
        ]
    finally:
        dialog.close()
        parent.close()


def test_upload_document_refreshes_calendar_when_dialog_emits(monkeypatch):
    class FakeSignal:
        def __init__(self):
            self._callback = None

        def connect(self, callback):
            self._callback = callback

        def emit(self, missionary_id, fields):
            self._callback(missionary_id, fields)

    class FakeUploadDialog:
        def __init__(self, missionary, parent=None):
            self.missionary = missionary
            self.parent = parent
            self.appointment_dates_updated = FakeSignal()

        def exec(self):
            self.appointment_dates_updated.emit(
                self.missionary.id,
                ["pickup_appointment_date"],
            )

        def saved_any(self):
            return False

    calendar = SimpleNamespace(load_count=0)

    def load_data():
        calendar.load_count += 1

    calendar.load_data = load_data
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.current_missionary = SimpleNamespace(id=7)
    page.main_window = SimpleNamespace(calendar_page=calendar)

    monkeypatch.setattr(
        detail_module,
        "UploadSessionDialog",
        FakeUploadDialog,
    )

    detail_module.MissionaryDetailPage.upload_document(page)

    assert calendar.load_count == 1


def test_supported_upload_files_from_paths_expands_folder():
    root = Path("test_upload_tmp") / str(uuid4())
    try:
        folder = root / "missionary"
        nested = folder / "nested"
        nested.mkdir(parents=True)
        pdf = folder / "passport.pdf"
        image = nested / "photo.JPG"
        unsupported = nested / "notes.txt"
        pdf.write_text("pdf")
        image.write_text("image")
        unsupported.write_text("notes")

        files = supported_upload_files_from_paths([folder])

        assert files == [str(pdf), str(image)]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_supported_upload_files_from_paths_keeps_direct_files():
    root = Path("test_upload_tmp") / str(uuid4())
    try:
        root.mkdir(parents=True)
        pdf = root / "visa.pdf"
        unsupported = root / "notes.docx"
        pdf.write_text("pdf")
        unsupported.write_text("doc")

        files = supported_upload_files_from_paths([pdf, unsupported])

        assert files == [str(pdf)]
    finally:
        shutil.rmtree(root, ignore_errors=True)
