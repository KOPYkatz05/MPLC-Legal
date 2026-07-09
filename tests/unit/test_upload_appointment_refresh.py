import shutil
from datetime import date
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.document import Document
from services import document_service as document_service_module
from services.document_service import DocumentService
from ui.dialogs.upload_session_dialog import (
    UploadSessionController,
    UploadSessionDialog,
    UploadSaveProgressDialog,
    supported_upload_files_from_paths,
)
from services.upload_pipeline import UploadPipelineResult
from ui.dialogs import upload_session_dialog
from ui.pages import missionary_detail_page as detail_module
from utils.constants import DOCUMENTS
from utils.i18n import get_i18n


def _build_upload_dialog(qapp):
    parent = QWidget()
    parent.resize(1200, 800)
    missionary = SimpleNamespace(id=42, full_name="Test Missionary")
    dialog = UploadSessionDialog(missionary, parent=parent)
    return dialog, parent


def test_upload_drop_zone_uses_active_language(qapp):
    i18n = get_i18n()
    original_language = i18n.get_language()
    try:
        i18n.set_language("en")
        dialog, parent = _build_upload_dialog(qapp)
        labels = {
            label.text()
            for label in dialog.findChildren(QLabel)
        }
        buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
        }
        browse_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Browse"
        )

        assert "Drop files or folders here, or browse" in labels
        assert "No files selected yet." in labels
        assert "Browse" in buttons
        assert [action.text() for action in browse_button.menu().actions()] == [
            "Files...",
            "Folder...",
        ]

        dialog.deleteLater()
        parent.deleteLater()

        i18n.set_language("es")
        dialog, parent = _build_upload_dialog(qapp)
        labels = {
            label.text()
            for label in dialog.findChildren(QLabel)
        }
        buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
        }

        assert "Arrastre archivos o carpetas aquí, o busque" in labels
        assert "Todavía no hay archivos seleccionados." in labels
        assert "Buscar" in buttons
        dialog.deleteLater()
        parent.deleteLater()
    finally:
        i18n.set_language(original_language)


def test_upload_dialog_uses_settings_for_auto_ocr_and_hides_save_current(qapp):
    dialog, parent = _build_upload_dialog(qapp)
    try:
        buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
        }
        assert "Save Current" not in buttons

        dialog.settings_service = SimpleNamespace(
            get_upload_auto_ocr_enabled=lambda: False
        )
        assert dialog._auto_ocr_enabled() is False

        dialog.settings_service = SimpleNamespace(
            get_upload_auto_ocr_enabled=lambda: True
        )
        assert dialog._auto_ocr_enabled() is True
    finally:
        dialog.deleteLater()
        parent.deleteLater()


def test_upload_save_progress_fill_gets_visible_width(qapp):
    parent = QWidget()
    parent.resize(640, 360)
    dialog = UploadSaveProgressDialog(parent)
    try:
        dialog.progress_track.resize(300, 8)
        dialog.set_progress(1, 3)
        dialog._set_progress_fill_width(animated=False)

        assert dialog.progress_fill.width() > 0
        assert dialog.progress_fill.width() <= dialog.progress_track.width()
    finally:
        dialog.deleteLater()
        parent.deleteLater()


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
    page._reload_missionary = lambda: None

    monkeypatch.setattr(
        detail_module,
        "UploadSessionDialog",
        FakeUploadDialog,
    )

    detail_module.MissionaryDetailPage.upload_document(page)

    assert calendar.load_count == 1


def test_upload_document_reloads_detail_when_appointment_date_emits(monkeypatch):
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
                ["interpol_appointment_date"],
            )

        def saved_any(self):
            return False

    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.current_missionary = SimpleNamespace(id=7)
    page.main_window = SimpleNamespace(calendar_page=None)
    page.reload_count = 0

    def reload_missionary():
        page.reload_count += 1

    page._reload_missionary = reload_missionary

    monkeypatch.setattr(
        detail_module,
        "UploadSessionDialog",
        FakeUploadDialog,
    )

    detail_module.MissionaryDetailPage.upload_document(page)

    assert page.reload_count == 1


def test_upload_document_refreshes_missionaries_table_after_save(monkeypatch):
    class FakeSignal:
        def connect(self, callback):
            self._callback = callback

    class FakeUploadDialog:
        def __init__(self, missionary, parent=None):
            self.missionary = missionary
            self.parent = parent
            self.appointment_dates_updated = FakeSignal()

        def exec(self):
            return None

        def saved_any(self):
            return True

    missionaries_page = SimpleNamespace(load_count=0)

    def load_data():
        missionaries_page.load_count += 1

    missionaries_page.load_data = load_data
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.current_missionary = SimpleNamespace(id=7)
    page.main_window = SimpleNamespace(
        missionaries_page=missionaries_page,
    )
    page._reload_missionary = lambda: None

    monkeypatch.setattr(
        detail_module,
        "UploadSessionDialog",
        FakeUploadDialog,
    )

    detail_module.MissionaryDetailPage.upload_document(page)

    assert missionaries_page.load_count == 1


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


def test_carne_upload_only_reviews_issue_date_not_residency_expiration():
    config = DOCUMENTS["CARNE_DE_EXTRANJERIA"]

    assert "carnet_issue_date" in config["ocr_fields"]
    assert "residency_expiration" not in config["ocr_fields"]
    assert "residency_expiration" not in config["auto_updates"]


def test_constancia_de_prorroga_is_selectable_without_ocr():
    config = DOCUMENTS["CONSTANCIA_DE_PRORROGA"]

    assert config["label"] == "Constancia de Prórroga"
    assert config["stage"] == "PRORROGA"
    assert config["required"] is False
    assert config["ocr_fields"] == []
    assert config["auto_updates"] == []


def test_upload_controller_prefills_ocr_fields_from_missionary():
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        passport_number="  X1234567  ",
        date_of_birth=date(2001, 2, 3),
        nationality="USA",
        passport_expiration=date(2031, 4, 5),
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["passport.pdf"])

    controller.set_document_type(0, "PASSPORT")

    assert controller.items[0].confirmed_data == {
        "full_name": "Test Missionary",
        "passport_number": "X1234567",
        "date_of_birth": "2001-02-03",
        "nationality": "USA",
        "passport_expiration": "2031-04-05",
    }


def test_upload_controller_omits_blank_missionary_defaults():
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        tramite_usuario=" elder.user ",
        tramite_contrasena="  ",
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["tramite.pdf"])

    controller.set_document_type(
        0,
        "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
    )

    assert controller.items[0].confirmed_data == {
        "tramite_usuario": "elder.user",
    }


def test_passport_ocr_replaces_prefilled_values_with_mrz_data(
    monkeypatch,
):
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        passport_number="EXISTING123",
        date_of_birth=None,
        nationality="USA",
        passport_expiration=None,
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["passport.pdf"])
    controller.set_document_type(0, "PASSPORT")
    item = controller.items[0]

    def fake_prepare_ocr_ingestion(**kwargs):
        return UploadPipelineResult(
            parsed_data={
                "full_name": "OCR PASSPORT NAME",
                "passport_number": "OCR999999",
                "date_of_birth": "2002-03-04",
                "passport_expiration": "2032-05-06",
            },
            ocr_status="success",
        )

    monkeypatch.setattr(
        upload_session_dialog,
        "prepare_ocr_ingestion",
        fake_prepare_ocr_ingestion,
    )

    controller.run_ocr(item)

    assert item.confirmed_data == {
        "full_name": "OCR PASSPORT NAME",
        "passport_number": "OCR999999",
        "nationality": "USA",
        "date_of_birth": "2002-03-04",
        "passport_expiration": "2032-05-06",
    }


def test_non_passport_ocr_fills_blank_without_overwriting_existing(
    monkeypatch,
):
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        pickup_appointment_date=date(2026, 1, 2),
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["recojo.pdf"])
    controller.set_document_type(0, "CITA_RECOJO")
    item = controller.items[0]

    def fake_prepare_ocr_ingestion(**kwargs):
        return UploadPipelineResult(
            parsed_data={
                "pickup_appointment_date": "2026-03-04",
            },
            ocr_status="success",
        )

    monkeypatch.setattr(
        upload_session_dialog,
        "prepare_ocr_ingestion",
        fake_prepare_ocr_ingestion,
    )

    controller.run_ocr(item)

    assert item.confirmed_data == {
        "pickup_appointment_date": "2026-01-02",
    }


def test_passport_ocr_does_not_overwrite_manual_confirmed_value(
    monkeypatch,
):
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        passport_number="EXISTING123",
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["passport.pdf"])
    controller.set_document_type(0, "PASSPORT")
    item = controller.items[0]
    item.confirmed_data["passport_number"] = "MANUAL123"

    def fake_prepare_ocr_ingestion(**kwargs):
        return UploadPipelineResult(
            parsed_data={
                "passport_number": "OCR999999",
            },
            ocr_status="success",
        )

    monkeypatch.setattr(
        upload_session_dialog,
        "prepare_ocr_ingestion",
        fake_prepare_ocr_ingestion,
    )

    controller.run_ocr(item)

    assert item.confirmed_data["passport_number"] == "MANUAL123"


def test_upload_ocr_does_not_overwrite_manual_confirmed_value(
    monkeypatch,
):
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        biometric_appointment_date=None,
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["biometric.pdf"])
    controller.set_document_type(0, "CONSTANCIA_DE_CITA_BIOMETRICO")
    item = controller.items[0]
    item.confirmed_data = {
        "biometric_appointment_date": "2026-01-02",
    }

    def fake_prepare_ocr_ingestion(**kwargs):
        return UploadPipelineResult(
            parsed_data={
                "biometric_appointment_date": "2026-03-04",
            },
            ocr_status="success",
        )

    monkeypatch.setattr(
        upload_session_dialog,
        "prepare_ocr_ingestion",
        fake_prepare_ocr_ingestion,
    )

    controller.run_ocr(item)

    assert item.confirmed_data == {
        "biometric_appointment_date": "2026-01-02",
    }


def test_upload_save_never_runs_ocr(monkeypatch):
    missionary = SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        folder_path="unused",
    )
    controller = UploadSessionController(missionary)
    controller.add_files(["passport.pdf"])
    controller.set_document_type(0, "PASSPORT")
    item = controller.items[0]
    item.ocr_result = None
    item.notes = "Reviewed OCR fields."
    item.confirmed_data = {
        "passport_number": "MANUAL123",
    }

    def fail_if_ocr_runs(*args, **kwargs):
        raise AssertionError("Saving must not run OCR")

    captured = {}

    def fake_finalize_ocr_ingestion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            document=SimpleNamespace(id=123),
            updated_fields=[],
        )

    monkeypatch.setattr(controller, "run_ocr", fail_if_ocr_runs)
    monkeypatch.setattr(
        upload_session_dialog,
        "finalize_ocr_ingestion",
        fake_finalize_ocr_ingestion,
    )

    result = controller.save_item(item, run_ocr=True)

    assert result.succeeded
    assert captured["confirmed_data"] == {
        "passport_number": "MANUAL123",
    }
    assert captured["notes"] == "Reviewed OCR fields."
    assert captured["pipeline_result"].ocr_status == "skipped"


def test_document_upload_persists_notes(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(
        document_service_module,
        "SessionLocal",
        testing_session,
    )

    service = DocumentService()
    monkeypatch.setattr(
        service.workflow_validator,
        "validate_workflows",
        lambda *_args, **_kwargs: None,
    )

    root = Path("test_upload_tmp") / str(uuid4())
    try:
        root.mkdir(parents=True)
        source = root / "source.pdf"
        source.write_text("pdf")
        missionary = SimpleNamespace(
            id=42,
            full_name="Test Missionary",
            folder_path=str(root / "missionary"),
        )

        document = service.upload_document(
            missionary=missionary,
            source_file=source,
            document_type="PAGO_INTERPOL",
            workflow_stage="INTERPOL",
            notes="Reviewed and complete.",
        )

        session = testing_session()
        try:
            saved = session.query(Document).filter_by(id=document.id).one()
            assert saved.notes == "Reviewed and complete."
        finally:
            session.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)
