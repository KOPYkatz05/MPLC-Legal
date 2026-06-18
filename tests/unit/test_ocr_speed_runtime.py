from types import SimpleNamespace

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from ui.dialogs import upload_session_dialog
from ui.dialogs.upload_session_dialog import (
    UploadOcrWarmupWorker,
    UploadSessionDialog,
)
from services import upload_pipeline


def test_ocr_runtime_mode_defaults_to_subprocess(monkeypatch):
    monkeypatch.delenv("MISSION_LEGAL_OCR_MODE", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_OCR_IN_PROCESS", raising=False)

    assert upload_pipeline.ocr_runtime_mode() == "subprocess"


def test_ocr_runtime_mode_honors_subprocess(monkeypatch):
    monkeypatch.setenv("MISSION_LEGAL_OCR_MODE", "subprocess")
    monkeypatch.delenv("MISSION_LEGAL_OCR_IN_PROCESS", raising=False)

    assert upload_pipeline.ocr_runtime_mode() == "subprocess"


def test_ocr_runtime_mode_honors_in_process(monkeypatch):
    monkeypatch.setenv("MISSION_LEGAL_OCR_MODE", "in_process")
    monkeypatch.delenv("MISSION_LEGAL_OCR_IN_PROCESS", raising=False)

    assert upload_pipeline.ocr_runtime_mode() == "in_process"


def test_ocr_runtime_mode_keeps_legacy_in_process_alias(monkeypatch):
    monkeypatch.delenv("MISSION_LEGAL_OCR_MODE", raising=False)
    monkeypatch.setenv("MISSION_LEGAL_OCR_IN_PROCESS", "1")

    assert upload_pipeline.ocr_runtime_mode() == "in_process"


def test_extract_ocr_texts_defaults_to_subprocess(monkeypatch):
    monkeypatch.delenv("MISSION_LEGAL_OCR_MODE", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_OCR_IN_PROCESS", raising=False)
    monkeypatch.setattr(upload_pipeline, "_ocr_service", None)
    monkeypatch.setattr(upload_pipeline, "_ocr_init_failed", False)
    monkeypatch.setattr(
        upload_pipeline,
        "_extract_ocr_texts_subprocess",
        lambda image_paths: [{"text": "subprocess"}],
    )

    def fail_in_process(image_paths, parent=None):
        raise AssertionError("in-process OCR should not run by default")

    monkeypatch.setattr(
        upload_pipeline,
        "_extract_ocr_texts_in_process",
        fail_in_process,
    )

    assert upload_pipeline.extract_ocr_texts(["page.png"]) == [
        {"text": "subprocess"}
    ]


def test_extract_ocr_texts_honors_subprocess_mode(monkeypatch):
    monkeypatch.setenv("MISSION_LEGAL_OCR_MODE", "subprocess")
    monkeypatch.setattr(upload_pipeline, "_ocr_service", object())
    monkeypatch.setattr(upload_pipeline, "_ocr_init_failed", False)
    monkeypatch.setattr(
        upload_pipeline,
        "_extract_ocr_texts_subprocess",
        lambda image_paths: [{"text": "subprocess"}],
    )

    def fail_in_process(image_paths, parent=None):
        raise AssertionError("in-process OCR should not run in subprocess mode")

    monkeypatch.setattr(
        upload_pipeline,
        "_extract_ocr_texts_in_process",
        fail_in_process,
    )

    assert upload_pipeline.extract_ocr_texts(["page.png"]) == [
        {"text": "subprocess"}
    ]


def test_in_process_ocr_reuses_cached_service(monkeypatch):
    class FakeOcrService:
        def __init__(self):
            self.calls = 0

        def extract_page(self, image_path):
            self.calls += 1
            return {"text": image_path, "lines": []}

    service = FakeOcrService()
    monkeypatch.setattr(upload_pipeline, "_ocr_service", service)
    monkeypatch.setattr(upload_pipeline, "_ocr_init_failed", False)

    pages = upload_pipeline._extract_ocr_texts_in_process(
        ["one.png", "two.png"]
    )

    assert service.calls == 2
    assert [page["text"] for page in pages] == ["one.png", "two.png"]


def test_upload_dialog_show_schedules_ocr_warmup(monkeypatch, qapp):
    started = []
    monkeypatch.setattr(
        UploadSessionDialog,
        "_start_ocr_warmup",
        lambda self: started.append(True),
    )
    parent = QWidget()
    parent.resize(1200, 800)
    dialog = UploadSessionDialog(
        SimpleNamespace(id=42, full_name="Test Missionary"),
        parent=parent,
    )

    try:
        dialog.showEvent(QShowEvent())
        qapp.processEvents()

        assert started
    finally:
        dialog.close()
        parent.close()


def test_upload_ocr_warmup_skips_service_in_subprocess_mode(monkeypatch):
    monkeypatch.delenv("MISSION_LEGAL_OCR_MODE", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_OCR_IN_PROCESS", raising=False)

    def fail_get_ocr_service(parent=None):
        raise AssertionError("subprocess mode should skip OCR warmup service")

    monkeypatch.setattr(
        upload_session_dialog,
        "get_ocr_service",
        fail_get_ocr_service,
    )

    dialog = UploadSessionDialog.__new__(UploadSessionDialog)
    dialog._is_closing = False
    dialog._ocr_warmup_started = False

    UploadSessionDialog._start_ocr_warmup(dialog)

    assert dialog._ocr_warmup_started is True


def test_upload_ocr_warmup_worker_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        upload_session_dialog,
        "get_ocr_service",
        lambda parent=None: None,
    )
    worker = UploadOcrWarmupWorker()
    emitted = []
    worker.finished.connect(
        lambda ok, error: emitted.append((ok, error))
    )

    worker.run()

    assert emitted == [(False, "OCR service unavailable.")]
