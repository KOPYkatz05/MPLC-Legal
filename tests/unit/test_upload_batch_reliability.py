import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image
from PySide6.QtWidgets import QWidget

from services.document_service import DocumentUploadOutcomeUnknownError
from ui.dialogs import upload_session_dialog
from ui.dialogs.upload_session_dialog import (
    UploadQueueItem,
    UploadSaveResult,
    UploadSessionController,
    UploadSessionDialog,
    classify_upload_paths,
    supported_upload_files_from_paths,
)


def _test_root():
    root = Path("test_upload_tmp") / str(uuid4())
    root.mkdir(parents=True)
    return root


def _write_image(path, image_format=None):
    Image.new("RGB", (8, 8), "white").save(path, format=image_format)
    return path


def _missionary():
    return SimpleNamespace(
        id=42,
        full_name="Test Missionary",
        nationality="PERU",
        folder_path="unused",
    )


def _wait_for_batch(qapp, dialog, timeout=5.0):
    deadline = time.monotonic() + timeout
    while dialog._saving_all and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert not dialog._saving_all


def test_queue_items_use_stable_unique_upload_ids_and_keep_by_default():
    first = UploadQueueItem("first.pdf")
    second = UploadQueueItem("second.pdf")

    assert first.duplicate_action == "keep"
    assert first.upload_id
    assert first.upload_id != second.upload_id
    assert first.upload_id == first.upload_id


def test_supported_file_discovery_includes_jfif_and_webp():
    root = _test_root()
    try:
        jfif = _write_image(root / "front.jfif", "JPEG")
        webp = _write_image(root / "back.webp", "WEBP")

        assert supported_upload_files_from_paths([root]) == [
            str(webp),
            str(jfif),
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_classify_upload_paths_reports_unsupported_and_missing_paths():
    root = _test_root()
    try:
        valid = _write_image(root / "scan.jpg")
        unsupported = root / "notes.txt"
        unsupported.write_text("not a document")
        missing = root / "missing.pdf"

        accepted, rejected = classify_upload_paths(
            [valid, unsupported, missing]
        )

        assert accepted == [str(valid)]
        assert rejected == [
            (str(unsupported), "Unsupported file type: .txt"),
            (str(missing), "The file is missing or is not a regular file."),
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_explicit_replace_uploads_before_superseding_exact_document():
    root = _test_root()
    try:
        source = _write_image(root / "scan.jpg")
        calls = []

        class FakeDocumentService:
            def get_active_document_by_type(self, missionary_id, document_type):
                calls.append(("resolve", missionary_id, document_type))
                return SimpleNamespace(id=87)

            def upload_document(self, **kwargs):
                calls.append(("upload", kwargs))
                return SimpleNamespace(id=123)

            def delete_document_by_type(self, *_args, **_kwargs):
                raise AssertionError("replacement must never pre-delete")

        controller = UploadSessionController(
            _missionary(),
            document_service=FakeDocumentService(),
        )
        controller.add_files([source])
        controller.set_document_type(0, "PAGO_INTERPOL")
        item = controller.items[0]
        item.duplicate_action = "replace"
        original_upload_id = item.upload_id

        result = controller.save_item(item)

        assert result.succeeded
        assert calls[0] == ("resolve", 42, "PAGO_INTERPOL")
        uploaded = calls[1][1]
        assert uploaded["upload_id"] == original_upload_id
        assert uploaded["supersedes_document_id"] == 87
        assert item.supersedes_document_id == 87
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_postprocessing_warning_keeps_document_saved_and_visible(monkeypatch):
    root = _test_root()
    try:
        source = _write_image(root / "carne.jpg")
        controller = UploadSessionController(
            _missionary(),
            document_service=SimpleNamespace(),
        )
        controller.add_files([source])
        controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = controller.items[0]
        monkeypatch.setattr(
            upload_session_dialog,
            "finalize_ocr_ingestion",
            lambda **_kwargs: SimpleNamespace(
                document=SimpleNamespace(id=321),
                updated_fields=[],
                warnings=["Residency dates could not be refreshed."],
            ),
        )

        result = controller.save_item(item)

        assert result.succeeded
        assert item.status == "saved"
        assert item.saved_document_id == 321
        assert item.warnings == ["Residency dates could not be refreshed."]
        assert "Saved with a follow-up warning" in item.error_text
        assert UploadSessionDialog.status_text(item) == "Saved with warning"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_carne_back_scan_cannot_restore_stale_prefilled_metadata(monkeypatch):
    root = _test_root()
    try:
        front_path = _write_image(root / "carne-front.jpg")
        back_path = _write_image(root / "carne-back.jpg")
        missionary = _missionary()
        missionary.carnet_number = "OLD-123"
        missionary.carnet_issue_date = "2024-01-02"
        controller = UploadSessionController(
            missionary,
            document_service=SimpleNamespace(),
        )
        controller.add_files([front_path, back_path])
        for index in range(2):
            controller.set_document_type(index, "CARNE_DE_EXTRANJERIA")

        front, back = controller.items
        front.ocr_result = upload_session_dialog.UploadPipelineResult(
            parsed_data={
                "carnet_number": "NEW-987",
                "carnet_issue_date": "2026-08-14",
            }
        )
        controller.merge_ocr_data_into_confirmed(front)
        assert front.confirmed_data == {
            "carnet_number": "NEW-987",
            "carnet_issue_date": "2026-08-14",
        }
        assert back.confirmed_data == {
            "carnet_number": "OLD-123",
            "carnet_issue_date": "2024-01-02",
        }

        saved_updates = []

        def fake_finalize(**kwargs):
            saved_updates.append(dict(kwargs["confirmed_data"]))
            return SimpleNamespace(
                document=SimpleNamespace(id=len(saved_updates)),
                updated_fields=[],
                warnings=[],
            )

        monkeypatch.setattr(
            upload_session_dialog,
            "finalize_ocr_ingestion",
            fake_finalize,
        )

        assert controller.save_item(front).succeeded
        assert controller.save_item(back).succeeded

        assert saved_updates == [
            {
                "carnet_number": "NEW-987",
                "carnet_issue_date": "2026-08-14",
            },
            {},
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_saved_postprocessing_warning_can_be_retried_with_same_upload_id(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        source = _write_image(root / "carne.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = dialog.controller.items[0]
        original_upload_id = item.upload_id
        attempts = []

        def fake_save(current, **_kwargs):
            attempts.append(current.upload_id)
            current.status = "saved"
            current.warnings = (
                ["Residency dates could not be refreshed."]
                if len(attempts) == 1
                else []
            )
            current.error_text = "warning" if current.warnings else ""
            return UploadSaveResult(
                item=current,
                status="saved",
                document=SimpleNamespace(id=321),
                warnings=list(current.warnings),
            )

        monkeypatch.setattr(dialog.controller, "save_item", fake_save)

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert attempts == [original_upload_id]
        assert item.warnings
        assert dialog.save_all_btn.isEnabled()

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert attempts == [original_upload_id, original_upload_id]
        assert item.status == "saved"
        assert item.warnings == []
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_saved_carne_follow_up_retry_does_not_need_original_source(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        source = _write_image(root / "carne.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = dialog.controller.items[0]
        item.status = "saved"
        item.saved_document_id = 321
        item.warnings = ["Missionary updates still need to be retried."]
        source.unlink()
        retry_calls = []

        class FakeDocumentService:
            def retry_document_post_processing(self, document_id):
                retry_calls.append(document_id)
                return SimpleNamespace(
                    id=document_id,
                    post_processing_status="COMPLETE",
                    post_processing_updated_fields='["residency_expiration"]',
                )

        dialog.controller.document_service = FakeDocumentService()
        monkeypatch.setattr(
            upload_session_dialog,
            "finalize_saved_ocr_follow_up",
            lambda **kwargs: SimpleNamespace(
                document=kwargs["document"],
                updated_fields=["residency_expiration"],
                warnings=[],
            ),
        )

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert retry_calls == [321]
        assert not source.exists()
        assert item.status == "saved"
        assert item.warnings == []
        assert item.updated_fields == ["residency_expiration"]
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_saved_follow_up_transport_failure_remains_saved():
    root = _test_root()
    try:
        source = _write_image(root / "carne.jpg")

        class FakeDocumentService:
            def retry_document_post_processing(self, _document_id):
                raise RuntimeError("server unavailable")

        controller = UploadSessionController(
            _missionary(),
            document_service=FakeDocumentService(),
        )
        controller.add_files([source])
        controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = controller.items[0]
        item.status = "saved"
        item.saved_document_id = 321
        item.warnings = ["Missionary updates still need to be retried."]
        source.unlink()

        result = controller.save_item(item)

        assert result.status == "saved"
        assert item.status == "saved"
        assert item.saved_document_id == 321
        assert "could not be verified" in item.warnings[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unknown_outcome_retries_with_same_upload_identity():
    root = _test_root()
    try:
        source = _write_image(root / "scan.jpg")
        seen_upload_ids = []
        seen_replacement_ids = []
        resolved_ids = iter((87, 999))

        class FakeDocumentService:
            def get_active_document_by_type(self, *_args):
                return SimpleNamespace(id=next(resolved_ids))

            def upload_document(self, **kwargs):
                seen_upload_ids.append(kwargs["upload_id"])
                seen_replacement_ids.append(
                    kwargs["supersedes_document_id"]
                )
                if len(seen_upload_ids) == 1:
                    raise DocumentUploadOutcomeUnknownError(
                        "The server response was lost.",
                        upload_id=kwargs["upload_id"],
                    )
                return SimpleNamespace(id=456)

        controller = UploadSessionController(
            _missionary(),
            document_service=FakeDocumentService(),
        )
        controller.add_files([source])
        controller.set_document_type(0, "PAGO_INTERPOL")
        item = controller.items[0]
        item.duplicate_action = "replace"

        first_result = controller.save_item(item)
        assert controller.has_saved_items()
        second_result = controller.save_item(item)

        assert first_result.status == "unknown"
        assert item.status == "saved"
        assert second_result.succeeded
        assert seen_upload_ids == [item.upload_id, item.upload_id]
        assert seen_replacement_ids == [87, 87]
        assert next(resolved_ids) == 999
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unknown_carne_reconciles_after_original_source_is_deleted():
    root = _test_root()
    try:
        source = _write_image(root / "carne-front.jpg")
        upload_calls = []
        reconciliation_calls = []
        replacement_lookups = []

        class FakeDocumentService:
            def get_active_document_by_type(self, *_args):
                replacement_lookups.append(True)
                return SimpleNamespace(id=87)

            def upload_document(self, **kwargs):
                upload_calls.append(kwargs)
                raise DocumentUploadOutcomeUnknownError(
                    "The server response was lost.",
                    upload_id=kwargs["upload_id"],
                )

            def reconcile_upload(self, upload_id, **expected):
                reconciliation_calls.append((upload_id, expected))
                return SimpleNamespace(
                    id=456,
                    post_processing_status="COMPLETE",
                    post_processing_updated_fields="[]",
                )

        controller = UploadSessionController(
            _missionary(),
            document_service=FakeDocumentService(),
        )
        controller.add_files([source])
        controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = controller.items[0]
        item.duplicate_action = "replace"

        first_result = controller.save_item(item)
        cached_size = item.file_size
        cached_sha256 = item.content_sha256
        source.unlink()
        second_result = controller.save_item(item)

        assert first_result.status == "unknown"
        assert second_result.succeeded
        assert item.status == "saved"
        assert item.saved_document_id == 456
        assert len(upload_calls) == 1
        assert upload_calls[0]["content_sha256"] == cached_sha256
        assert upload_calls[0]["file_size"] == cached_size
        assert replacement_lookups == [True]
        assert reconciliation_calls == [
            (
                item.upload_id,
                {
                    "missionary_id": 42,
                    "document_type": "CARNE_DE_EXTRANJERIA",
                    "workflow_stage": item.workflow_stage,
                    "content_sha256": cached_sha256,
                    "file_size": cached_size,
                    "supersedes_document_id": 87,
                },
            )
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_all_reconciles_unknown_carne_when_source_was_deleted(qapp):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        source = _write_image(root / "carne-back.jpg")
        reconciliation_calls = []

        class FakeDocumentService:
            def reconcile_upload(self, upload_id, **expected):
                reconciliation_calls.append((upload_id, expected))
                return SimpleNamespace(
                    id=912,
                    post_processing_status="COMPLETE",
                    post_processing_updated_fields="[]",
                )

        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.controller.document_service = FakeDocumentService()
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "CARNE_DE_EXTRANJERIA")
        item = dialog.controller.items[0]
        dialog.controller._capture_content_identity(item)
        item.status = "unknown"
        source.unlink()

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert item.status == "saved"
        assert item.saved_document_id == 912
        assert len(reconciliation_calls) == 1
        assert reconciliation_calls[0][0] == item.upload_id
        assert reconciliation_calls[0][1]["content_sha256"] == item.content_sha256
        assert reconciliation_calls[0][1]["file_size"] == item.file_size
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_save_all_preflight_blocks_every_file_when_any_item_is_invalid(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        valid = _write_image(root / "unclassified.jpg")
        corrupt = root / "corrupt.jpg"
        corrupt.write_bytes(b"not an image")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([valid, corrupt])
        dialog.controller.set_document_type(1, "PAGO_INTERPOL")
        monkeypatch.setattr(
            dialog.controller,
            "save_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("preflight must prevent all uploads")
            ),
        )

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert [item.status for item in dialog.controller.items] == [
            "failed",
            "failed",
        ]
        assert "Select a document type" in dialog.controller.items[0].error_text
        assert "valid PDF or image" in dialog.controller.items[1].error_text
        assert "2 file(s) need attention" in dialog.status_label.text()
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_preflight_blocks_mixed_keep_and_replace_for_same_document_type(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        front = _write_image(root / "front.jpg")
        back = _write_image(root / "back.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([front, back])
        for index in range(2):
            dialog.controller.set_document_type(
                index,
                "CARNE_DE_EXTRANJERIA",
            )
        dialog.controller.items[1].duplicate_action = "replace"
        monkeypatch.setattr(
            dialog.controller,
            "save_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("ambiguous mixed replacement must not upload")
            ),
        )

        dialog.save_all()

        assert [item.status for item in dialog.controller.items] == [
            "failed",
            "failed",
        ]
        assert all(
            "Replace cannot be mixed" in item.error_text
            for item in dialog.controller.items
        )
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_failed_batch_keeps_dialog_queue_open_and_retries_only_failure(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        first = _write_image(root / "front.jpg")
        second = _write_image(root / "back.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([first, second])
        for index in range(2):
            dialog.controller.set_document_type(
                index, "CARNE_DE_EXTRANJERIA"
            )

        attempts = []

        def fake_save(item, **_kwargs):
            attempts.append(item.file_name)
            if item.file_name == "front.jpg" and attempts.count("front.jpg") == 1:
                item.status = "failed"
                item.error_text = "temporary failure"
                return UploadSaveResult(
                    item=item,
                    status="failed",
                    error_text=item.error_text,
                )
            item.status = "saved"
            item.error_text = ""
            return UploadSaveResult(
                item=item,
                status="saved",
                document=SimpleNamespace(id=len(attempts)),
            )

        monkeypatch.setattr(dialog.controller, "save_item", fake_save)
        monkeypatch.setattr(
            dialog,
            "hide",
            lambda: (_ for _ in ()).throw(
                AssertionError("the upload workspace must remain visible")
            ),
        )
        monkeypatch.setattr(
            dialog,
            "load_detail",
            lambda: (_ for _ in ()).throw(
                AssertionError("batch saving must not render previews")
            ),
        )
        monkeypatch.setattr(
            upload_session_dialog.QTimer,
            "singleShot",
            lambda _delay, callback: callback(),
        )

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert attempts == ["front.jpg", "back.jpg"]
        assert [item.status for item in dialog.controller.items] == [
            "failed",
            "saved",
        ]
        assert dialog._is_closing is False
        assert "1 saved, 1 failed" in dialog.status_label.text()

        dialog.save_all()
        _wait_for_batch(qapp, dialog)

        assert attempts == ["front.jpg", "back.jpg", "front.jpg"]
        assert [item.status for item in dialog.controller.items] == [
            "saved",
            "saved",
        ]
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_rejected_initial_file_remains_visible_in_queue(qapp):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        unsupported = root / "scan.heic"
        unsupported.write_bytes(b"unsupported")

        dialog = UploadSessionDialog(
            _missionary(),
            initial_files=[unsupported],
            parent=parent,
        )

        assert len(dialog.controller.items) == 1
        assert dialog.controller.items[0].status == "rejected"
        assert "Unsupported file type: .heic" in (
            dialog.controller.items[0].error_text
        )
        assert "Rejected 1 file" in dialog.status_label.text()
        assert "Rejected" in dialog.queue_list.item(0).text()
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_drop_event_keeps_unsupported_file_visible(qapp):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        unsupported = root / "scan.heic"
        unsupported.write_bytes(b"unsupported")
        dialog = UploadSessionDialog(_missionary(), parent=parent)

        class FakeUrl:
            def isLocalFile(self):
                return True

            def toLocalFile(self):
                return str(unsupported)

        class FakeMimeData:
            def urls(self):
                return [FakeUrl()]

        class FakeDropEvent:
            accepted = False

            def mimeData(self):
                return FakeMimeData()

            def acceptProposedAction(self):
                self.accepted = True

        event = FakeDropEvent()
        dialog.dropEvent(event)

        assert event.accepted
        assert len(dialog.controller.items) == 1
        assert dialog.controller.items[0].status == "rejected"
        assert "Unsupported file type: .heic" in (
            dialog.controller.items[0].error_text
        )
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_unknown_outcome_cannot_be_removed_or_mutated_before_retry(qapp):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        source = _write_image(root / "scan.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "PAGO_INTERPOL")
        item = dialog.controller.items[0]
        item.status = "unknown"
        dialog.controller.select(0)
        dialog._set_queue_row(0)

        dialog._update_action_states()

        assert dialog.save_all_btn.isEnabled()
        assert not dialog.remove_btn.isEnabled()
        assert not dialog.type_combo.isEnabled()
        assert not dialog.stage_combo.isEnabled()
        assert not dialog.duplicate_combo.isEnabled()
        assert not dialog.notes_editor.isEnabled()
    finally:
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_unknown_outcome_blocks_dialog_close_until_reconciled(qapp):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    try:
        source = _write_image(root / "scan.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "PAGO_INTERPOL")
        dialog.controller.items[0].status = "unknown"

        dialog.reject()

        assert dialog._is_closing is False
        assert "still being verified" in dialog.status_label.text()
        assert dialog.controller.items[0].upload_id
    finally:
        if "dialog" in locals():
            dialog.controller.items[0].status = "failed"
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)


def test_save_all_keeps_qt_event_loop_responsive_during_network_wait(
    monkeypatch,
    qapp,
):
    root = _test_root()
    parent = QWidget()
    parent.resize(1200, 800)
    started = threading.Event()
    release = threading.Event()
    try:
        source = _write_image(root / "scan.jpg")
        dialog = UploadSessionDialog(_missionary(), parent=parent)
        dialog.add_files([source])
        dialog.controller.set_document_type(0, "PAGO_INTERPOL")

        def blocking_save(item, **_kwargs):
            started.set()
            assert release.wait(3.0)
            item.status = "saved"
            return UploadSaveResult(
                item=item,
                status="saved",
                document=SimpleNamespace(id=901),
            )

        monkeypatch.setattr(dialog.controller, "save_item", blocking_save)
        dialog.save_all()

        deadline = time.monotonic() + 2.0
        while not started.is_set() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        assert started.is_set()

        marker = []
        upload_session_dialog.QTimer.singleShot(0, lambda: marker.append(True))
        qapp.processEvents()
        assert marker == [True]

        release.set()
        _wait_for_batch(qapp, dialog)
        assert dialog.controller.items[0].status == "saved"
    finally:
        release.set()
        if "dialog" in locals():
            dialog.deleteLater()
        parent.deleteLater()
        shutil.rmtree(root, ignore_errors=True)
