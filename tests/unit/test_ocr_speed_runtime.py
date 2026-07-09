from types import SimpleNamespace

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from ui.dialogs import upload_session_dialog
from ui.dialogs.upload_session_dialog import (
    UploadOcrWarmupWorker,
    UploadQueueItem,
    UploadSessionDialog,
)
from ui.foundation import FluentLoadingDialog
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


def test_extract_ocr_texts_subprocess_hides_windows_worker(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path = command[command.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write('{"pages": [{"text": "ok"}]}')
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(upload_pipeline.subprocess, "run", fake_run)

    assert upload_pipeline._extract_ocr_texts_subprocess(["page.png"]) == [
        {"text": "ok"}
    ]

    if upload_pipeline.os.name == "nt":
        assert captured["kwargs"]["creationflags"] == getattr(
            upload_pipeline.subprocess,
            "CREATE_NO_WINDOW",
            0,
        )
        startupinfo = captured["kwargs"]["startupinfo"]
        assert startupinfo.dwFlags & upload_pipeline.subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == upload_pipeline.subprocess.SW_HIDE
    else:
        assert "startupinfo" not in captured["kwargs"]


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


def test_fluent_loading_dialog_rotates_busy_messages(qapp):
    parent = QWidget()
    parent.resize(640, 480)
    dialog = FluentLoadingDialog(
        parent,
        title="Reading document...",
        message="Waiting...",
    )

    try:
        dialog.show_busy(
            "Waiting...",
            rotating_messages=[
                "Reading the document...",
                "Looking for appointment details...",
            ],
            rotation_interval_ms=99999,
        )

        assert dialog._message_label.text() == "Reading the document..."

        dialog._advance_message_rotation()

        assert dialog._message_label.text() == (
            "Looking for appointment details..."
        )

        dialog.hide_busy()

        assert not dialog._message_rotation_timer.isActive()
        assert dialog._message_rotation_messages == []
    finally:
        dialog.close()
        parent.close()


def test_upload_ocr_async_passes_dynamic_loading_messages(monkeypatch):
    class FakeSignal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback, *args):
            _ = args
            self.callbacks.append(callback)

    class FakeThread:
        Priority = SimpleNamespace(LowPriority=0)

        def __init__(self, parent=None):
            _ = parent
            self.started = FakeSignal()
            self.finished = FakeSignal()
            self.started_with = None

        def start(self, priority=None):
            self.started_with = priority

        def deleteLater(self):
            pass

        def quit(self):
            pass

    class FakeWorker:
        def __init__(self, controller, index):
            self.controller = controller
            self.index = index
            self.finished = FakeSignal()

        def moveToThread(self, thread):
            self.thread = thread

        def run(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(upload_session_dialog, "QThread", FakeThread)
    monkeypatch.setattr(upload_session_dialog, "UploadOcrWorker", FakeWorker)

    item = UploadQueueItem(
        file_path="passport.pdf",
        document_type="PASSPORT",
    )
    captured_busy = {}
    dialog = UploadSessionDialog.__new__(UploadSessionDialog)
    dialog._busy = False
    dialog._is_closing = False
    dialog._pending_save_after_ocr = None
    dialog._ocr_thread = None
    dialog._ocr_worker = None
    dialog.controller = SimpleNamespace(
        items=[item],
        selected_index=0,
    )
    dialog.persist_current_editor_settings = lambda item: None
    dialog.refresh_queue = lambda: None
    dialog.update_progress = lambda: None
    dialog._refresh_selected_item_labels = lambda item: None
    dialog.apply_ocr_banner = lambda status, text: None
    dialog._update_action_states = lambda: None

    def capture_busy(*args, **kwargs):
        captured_busy["args"] = args
        captured_busy["kwargs"] = kwargs

    dialog._set_busy = capture_busy

    started = UploadSessionDialog._run_ocr_async(dialog, 0, reason="manual")

    assert started is True
    assert captured_busy["args"] == (
        True,
        "Reading fields from passport.pdf...",
    )
    assert captured_busy["kwargs"]["content_loading_overlay"] is True
    assert captured_busy["kwargs"]["content_loading_messages"] == [
        "Reading the document...",
        "Looking for appointment details...",
        "Saving extracted data...",
        "This can take a few seconds for large PDFs.",
    ]
