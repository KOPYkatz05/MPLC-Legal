import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

import services.upload_pipeline as upload_pipeline
from services.ocr_service import OCRService
from services.document_service import DocumentService
from ui.main_window import MainWindow
from ui.dialogs.document_viewer_dialog import (
    get_document_viewer_render_hints,
)
from ui.dialogs.upload_document_dialog import (
    UploadDocumentDialog,
)
from ui.dialogs.upload_session_dialog import (
    FLUENT_DIALOG_AVAILABLE,
    UploadSessionDialog,
    UploadSessionController,
)
from ui.foundation import create_combo_box
from ui.pages.missionary_detail_page import (
    open_document_with_default_app,
)


class FakeOcrService:
    def __init__(self, text_by_path):
        self.text_by_path = text_by_path

    def extract_text(self, image_path):
        return self.text_by_path.get(str(image_path), "")


class FakeCombo:
    def __init__(self, data, text):
        self._data = data
        self._text = text

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text


class FakeDocumentService:
    def __init__(self, duplicate=False, fail_upload=False):
        self.duplicate = duplicate
        self.fail_upload = fail_upload
        self.deleted = []
        self.uploaded = []

    def document_type_exists(self, missionary_id, document_type):
        return self.duplicate

    def delete_document_by_type(self, missionary_id, document_type):
        self.deleted.append((missionary_id, document_type))
        self.duplicate = False

    def upload_document(
        self,
        missionary,
        source_file,
        document_type,
        workflow_stage,
        ocr_raw_data=None,
        ocr_confirmed_data=None,
    ):
        if self.fail_upload:
            raise RuntimeError("save failed")
        self.uploaded.append({
            "missionary": missionary,
            "source_file": source_file,
            "document_type": document_type,
            "workflow_stage": workflow_stage,
            "ocr_raw_data": ocr_raw_data,
            "ocr_confirmed_data": ocr_confirmed_data,
        })
        return SimpleNamespace(id=len(self.uploaded))


class UploadRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ocr_service_initializes_with_paddleocr_module(self):
        fake_module = types.ModuleType("paddleocr")

        class FakePaddleOCR:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        fake_module.PaddleOCR = FakePaddleOCR

        with patch.dict(
            sys.modules,
            {"paddleocr": fake_module},
        ):
            service = OCRService()

        self.assertIsInstance(service.ocr, FakePaddleOCR)
        self.assertEqual(service.ocr.kwargs["lang"], "en")

    def test_ocr_pipeline_reports_service_unavailable(self):
        old_service = upload_pipeline._ocr_service
        old_failed = upload_pipeline._ocr_init_failed

        try:
            upload_pipeline._ocr_service = None
            upload_pipeline._ocr_init_failed = True

            result = upload_pipeline.run_ocr_on_images(
                image_paths=[Path("page1.png")],
                document_type="PASSPORT",
                ocr_fields=["passport_number"],
                export_settings={"pages": "all"},
            )

            self.assertEqual(result.ocr_status, "failed")
            self.assertTrue(result.errors)
            self.assertIn(
                "OCR service unavailable",
                result.errors[0],
            )
        finally:
            upload_pipeline._ocr_service = old_service
            upload_pipeline._ocr_init_failed = old_failed

    def test_pdf_ocr_defaults_to_all_pages(self):
        settings = upload_pipeline._normalize_ocr_export_settings(
            Path("passport.pdf"),
            {
                "page": 0,
                "rotation": 0,
                "crop_rect": None,
            },
        )

        self.assertEqual(settings["pages"], "all")

    def test_explicit_pdf_ocr_pages_are_preserved(self):
        settings = upload_pipeline._normalize_ocr_export_settings(
            Path("passport.pdf"),
            {
                "pages": [1],
                "page": 0,
                "rotation": 0,
                "crop_rect": None,
            },
        )

        self.assertEqual(settings["pages"], [1])

    def test_passport_ocr_pipeline_parses_expected_fields(self):
        old_service = upload_pipeline._ocr_service
        old_failed = upload_pipeline._ocr_init_failed
        image_paths = [Path("page1.png"), Path("page2.png")]

        try:
            upload_pipeline._ocr_service = FakeOcrService(
                {
                    str(image_paths[0]): "\n".join([
                        "P<USADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<<<<<",
                        "1234567897USA9001011M3001019<<<<<<<<<<<<<<06",
                    ]),
                    str(image_paths[1]): "",
                }
            )
            upload_pipeline._ocr_init_failed = False

            result = upload_pipeline.run_ocr_on_images(
                image_paths=image_paths,
                document_type="PASSPORT",
                ocr_fields=[
                    "passport_number",
                    "nationality",
                    "full_name",
                    "date_of_birth",
                    "passport_expiration",
                ],
                export_settings={"pages": "all"},
            )

            self.assertEqual(result.ocr_status, "success")
            self.assertEqual(
                result.parsed_data["passport_number"],
                "123456789",
            )
            self.assertEqual(
                result.parsed_data["nationality"],
                "USA",
            )
            self.assertEqual(
                result.parsed_data["full_name"],
                "DOE JOHN",
            )
            self.assertEqual(
                result.parsed_data["date_of_birth"],
                "1990-01-01",
            )
            self.assertEqual(
                result.parsed_data["passport_expiration"],
                "2030-01-01",
            )
            self.assertEqual(
                result.to_audit_payload()["status"],
                "success",
            )
        finally:
            upload_pipeline._ocr_service = old_service
            upload_pipeline._ocr_init_failed = old_failed

    def test_upload_session_prompts_for_ocr_review(self):
        pipeline_result = upload_pipeline.UploadPipelineResult(
            ocr_status="partial",
            document_type="PASSPORT",
            ocr_fields=["passport_number"],
            parsed_data={"passport_number": "123456789"},
        )

        controller = UploadSessionController(
            SimpleNamespace(id=1, current_stage="INTERPOL"),
            document_service=FakeDocumentService(),
        )
        controller.add_files(["doc.pdf"])
        item = controller.items[0]
        item.document_type = "PASSPORT"
        item.workflow_stage = "GENERAL"

        with patch(
            "ui.dialogs.upload_session_dialog.prepare_ocr_ingestion",
            return_value=pipeline_result,
        ), patch(
            "ui.dialogs.upload_session_dialog.OCRReviewDialog",
        ) as review_cls:
            review = review_cls.return_value
            review.exec.return_value = QDialog.Accepted
            review.get_data.return_value = {
                "passport_number": "987654321",
            }

            controller.run_ocr(item, review=True)

        self.assertTrue(item.ocr_reviewed)
        self.assertEqual(
            item.confirmed_data["passport_number"],
            "987654321",
        )

    def test_viewer_render_hints_use_qt_painter_flags(self):
        hints = get_document_viewer_render_hints()

        self.assertTrue(hints & QPainter.Antialiasing)
        self.assertTrue(hints & QPainter.SmoothPixmapTransform)

    def test_open_document_uses_windows_api_on_windows(self):
        with patch(
            "ui.pages.missionary_detail_page.sys.platform",
            "win32",
        ), patch(
            "ui.pages.missionary_detail_page.os.startfile",
            create=True,
        ) as startfile, patch(
            "ui.pages.missionary_detail_page.subprocess.Popen"
        ) as popen:
            open_document_with_default_app(
                r"C:\docs\passport.pdf"
            )

        startfile.assert_called_once_with(
            r"C:\docs\passport.pdf"
        )
        popen.assert_not_called()

    def test_open_document_uses_xdg_open_on_linux(self):
        with patch(
            "ui.pages.missionary_detail_page.sys.platform",
            "linux",
        ), patch(
            "ui.pages.missionary_detail_page.subprocess.Popen"
        ) as popen:
            open_document_with_default_app(
                "/tmp/passport.pdf"
            )

        popen.assert_called_once_with(
            ["xdg-open", "/tmp/passport.pdf"]
        )

    def test_duplicate_document_filenames_increment_suffix(self):
        folder = Path("test_output")
        with patch.object(
            Path,
            "exists",
            side_effect=[True, False],
        ):
            destination_path, file_name = (
                DocumentService._build_destination_path(
                    folder,
                    "PASSPORT",
                    ".pdf",
                )
            )

        self.assertEqual(file_name, "PASSPORT_1.pdf")
        self.assertEqual(
            destination_path.name,
            "PASSPORT_1.pdf",
        )

    def test_upload_document_requires_document_type(self):
        service = DocumentService()
        missionary = SimpleNamespace(
            id=1,
            full_name="Test Missionary",
            folder_path="test_output",
        )

        with self.assertRaisesRegex(
            ValueError,
            "document_type is required",
        ):
            service.upload_document(
                missionary=missionary,
                source_file="test_output/page_1.png",
                document_type=None,
                workflow_stage=None,
            )

    def test_upload_dialog_maps_label_to_document_key(self):
        dialog = UploadDocumentDialog.__new__(UploadDocumentDialog)
        dialog._label_to_key = {"Passport": "PASSPORT"}
        dialog.type_combo = FakeCombo(None, "Passport")

        self.assertEqual(
            UploadDocumentDialog.get_document_type(dialog),
            "PASSPORT",
        )

    def test_foundation_combo_preserves_item_data(self):
        combo = create_combo_box()
        combo.addItem("Passport", "PASSPORT")
        combo.addItem("TAM", "TAM")

        combo.setCurrentIndex(1)

        self.assertEqual(combo.currentText(), "TAM")
        self.assertEqual(combo.currentData(), "TAM")
        self.assertEqual(combo.findData("PASSPORT"), 0)
        self.assertEqual(combo.findData("TAM"), 1)

    def test_upload_session_adds_unique_supported_files(self):
        controller = UploadSessionController(
            SimpleNamespace(id=1, current_stage="INTERPOL"),
            document_service=FakeDocumentService(),
        )

        added = controller.add_files([
            "one.pdf",
            "one.pdf",
            "notes.txt",
            "photo.png",
        ])

        self.assertEqual(len(added), 2)
        self.assertEqual(len(controller.items), 2)
        self.assertEqual(controller.selected_index, 0)

    def test_upload_session_derives_stage_from_document_type(self):
        controller = UploadSessionController(
            SimpleNamespace(id=1),
            document_service=FakeDocumentService(),
        )
        controller.add_files(["doc.pdf"])

        controller.set_document_type(0, "TAM")

        self.assertEqual(
            controller.items[0].workflow_stage,
            "INTERPOL",
        )

    def test_upload_session_replace_duplicate_deletes_existing(self):
        service = FakeDocumentService(duplicate=True)
        controller = UploadSessionController(
            SimpleNamespace(id=7, current_stage="INTERPOL"),
            document_service=service,
        )
        controller.add_files(["doc.pdf"])
        item = controller.items[0]
        item.document_type = "PAGO_INTERPOL"
        item.workflow_stage = "INTERPOL"
        item.duplicate_action = "replace"

        controller.save_item(item)

        self.assertEqual(service.deleted, [(7, "PAGO_INTERPOL")])
        self.assertEqual(item.status, "saved")
        self.assertEqual(len(service.uploaded), 1)

    def test_upload_session_skip_duplicate_marks_skipped(self):
        service = FakeDocumentService(duplicate=True)
        controller = UploadSessionController(
            SimpleNamespace(id=7, current_stage="INTERPOL"),
            document_service=service,
        )
        controller.add_files(["doc.pdf"])
        item = controller.items[0]
        item.duplicate_action = "skip"

        controller.save_item(item)

        self.assertEqual(item.status, "skipped")
        self.assertEqual(service.uploaded, [])

    def test_upload_session_save_failure_leaves_error_visible(self):
        service = FakeDocumentService(fail_upload=True)
        controller = UploadSessionController(
            SimpleNamespace(id=7, current_stage="INTERPOL"),
            document_service=service,
        )
        controller.add_files(["doc.pdf"])
        item = controller.items[0]
        item.document_type = "PAGO_INTERPOL"
        item.workflow_stage = "INTERPOL"

        controller.save_item(item)

        self.assertEqual(item.status, "failed")
        self.assertIn("save failed", item.error_text)

    def test_upload_session_save_failure_does_not_advance(self):
        service = FakeDocumentService(fail_upload=True)
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.controller.document_service = service
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)

        dialog.save_current()

        self.assertEqual(dialog.controller.selected_index, 0)
        self.assertEqual(dialog.queue_list.currentRow(), 0)
        self.assertEqual(dialog.controller.items[0].status, "failed")
        self.assertEqual(dialog.controller.items[1].status, "pending")

        dialog.close()

    def test_upload_session_rejects_missing_document_type_before_save(self):
        service = FakeDocumentService()
        controller = UploadSessionController(
            SimpleNamespace(id=7, current_stage="INTERPOL"),
            document_service=service,
        )
        controller.add_files(["doc.pdf"])
        item = controller.items[0]
        item.document_type = None
        item.workflow_stage = None

        result = controller.save_item(item)

        self.assertEqual(result.status, "failed")
        self.assertEqual(item.status, "failed")
        self.assertIn("document_type is required", item.error_text)
        self.assertEqual(service.uploaded, [])

    def test_upload_session_keeps_per_file_ocr_state_when_navigating(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        dialog.field_edits["passport_number"].setText("P-12345")
        dialog.notes_editor.setPlainText("passport note")
        dialog.go_to_next_item()

        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)
        dialog.date_edits["arrival_date"].setDate(QDate(2025, 1, 2))
        dialog.notes_editor.setPlainText("tam note")
        dialog.go_to_next_item()

        first_item, second_item = dialog.controller.items
        self.assertEqual(first_item.confirmed_data["passport_number"], "P-12345")
        self.assertEqual(first_item.notes, "passport note")
        self.assertEqual(second_item.confirmed_data["arrival_date"], "2025-01-02")
        self.assertEqual(second_item.notes, "tam note")
        self.assertEqual(dialog.type_combo.currentData(), "PASSPORT")
        self.assertEqual(dialog.stage_combo.currentData(), "GENERAL")
        self.assertEqual(
            dialog.field_edits["passport_number"].text(),
            "P-12345",
        )

        dialog.close()

    def test_upload_session_queue_click_keeps_document_details_per_file(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        dialog.field_edits["passport_number"].setText("P-CLICK-1")
        dialog.notes_editor.setPlainText("first file note")

        dialog.queue_list.setCurrentRow(1)
        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)
        dialog.date_edits["arrival_date"].setDate(QDate(2025, 1, 2))
        dialog.notes_editor.setPlainText("second file note")

        dialog.queue_list.setCurrentRow(0)

        first_item, second_item = dialog.controller.items
        self.assertEqual(first_item.document_type, "PASSPORT")
        self.assertEqual(first_item.workflow_stage, "GENERAL")
        self.assertEqual(
            first_item.confirmed_data["passport_number"],
            "P-CLICK-1",
        )
        self.assertEqual(first_item.notes, "first file note")
        self.assertEqual(second_item.document_type, "TAM")
        self.assertEqual(second_item.workflow_stage, "INTERPOL")
        self.assertEqual(
            second_item.confirmed_data["arrival_date"],
            "2025-01-02",
        )
        self.assertEqual(second_item.notes, "second file note")
        self.assertEqual(dialog.type_combo.currentData(), "PASSPORT")
        self.assertEqual(dialog.stage_combo.currentData(), "GENERAL")
        self.assertEqual(
            dialog.field_edits["passport_number"].text(),
            "P-CLICK-1",
        )

        dialog.close()

    def test_upload_session_queue_card_click_selects_item(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        dialog.field_edits["passport_number"].setText("P-CARD-1")
        dialog.notes_editor.setPlainText("first card note")

        second_card = dialog.queue_list.itemWidget(dialog.queue_list.item(1))
        QTest.mouseClick(
            second_card,
            Qt.LeftButton,
            Qt.NoModifier,
            second_card.rect().center(),
        )
        self.app.processEvents()

        self.assertEqual(dialog.queue_list.currentRow(), 1)
        self.assertEqual(dialog.controller.selected_index, 1)
        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)
        dialog.date_edits["arrival_date"].setDate(QDate(2025, 1, 2))
        dialog.notes_editor.setPlainText("second card note")

        first_card = dialog.queue_list.itemWidget(dialog.queue_list.item(0))
        QTest.mouseClick(
            first_card,
            Qt.LeftButton,
            Qt.NoModifier,
            first_card.rect().center(),
        )
        self.app.processEvents()

        first_item, second_item = dialog.controller.items
        self.assertEqual(dialog.queue_list.currentRow(), 0)
        self.assertEqual(dialog.controller.selected_index, 0)
        self.assertEqual(first_item.document_type, "PASSPORT")
        self.assertEqual(first_item.workflow_stage, "GENERAL")
        self.assertEqual(
            first_item.confirmed_data["passport_number"],
            "P-CARD-1",
        )
        self.assertEqual(first_item.notes, "first card note")
        self.assertEqual(second_item.document_type, "TAM")
        self.assertEqual(second_item.workflow_stage, "INTERPOL")
        self.assertEqual(
            second_item.confirmed_data["arrival_date"],
            "2025-01-02",
        )
        self.assertEqual(second_item.notes, "second card note")
        self.assertEqual(dialog.type_combo.currentData(), "PASSPORT")
        self.assertEqual(dialog.stage_combo.currentData(), "GENERAL")

        dialog.close()

    def test_upload_session_swaps_document_type_and_stage_per_queue_item(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)
        self.assertEqual(dialog.stage_combo.currentData(), "INTERPOL")

        dialog.go_to_next_item()
        photo_idx = dialog.type_combo.findData("PHOTO")
        dialog.type_combo.setCurrentIndex(photo_idx)
        cancel_idx = dialog.stage_combo.findData("CANCELACION")
        dialog.stage_combo.setCurrentIndex(cancel_idx)

        self.assertEqual(dialog.controller.items[1].document_type, "PHOTO")
        self.assertEqual(dialog.controller.items[1].workflow_stage, "CANCELACION")

        dialog.go_to_next_item()
        self.assertEqual(dialog.type_combo.currentData(), "TAM")
        self.assertEqual(dialog.stage_combo.currentData(), "INTERPOL")

        dialog.go_to_next_item()
        self.assertEqual(dialog.type_combo.currentData(), "PHOTO")
        self.assertEqual(dialog.stage_combo.currentData(), "CANCELACION")

        dialog.close()

    def test_upload_session_passport_renders_ocr_fields(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["passport.pdf"])

        self.assertEqual(dialog.type_combo.currentData(), "PASSPORT")
        self.assertIn("passport_number", dialog.field_edits)
        self.assertNotIn(
            "does not use OCR fields",
            dialog.ocr_status_label.text().lower(),
        )

        dialog.close()

    def test_upload_session_type_change_only_clears_current_item_ocr_state(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])

        dialog.field_edits["passport_number"].setText("FIRST")
        dialog.go_to_next_item()

        tam_idx = dialog.type_combo.findData("TAM")
        dialog.type_combo.setCurrentIndex(tam_idx)
        dialog.date_edits["arrival_date"].setDate(QDate(2025, 1, 2))
        dialog.persist_current_item_state()

        photo_idx = dialog.type_combo.findData("PHOTO")
        dialog.type_combo.setCurrentIndex(photo_idx)

        first_item, second_item = dialog.controller.items
        self.assertEqual(first_item.confirmed_data["passport_number"], "FIRST")
        self.assertEqual(second_item.document_type, "PHOTO")
        self.assertEqual(second_item.confirmed_data, {})
        self.assertFalse(second_item.has_ocr_fields)
        self.assertNotIn(
            "passport_number",
            second_item.confirmed_data,
        )

        dialog.close()

    def test_upload_session_navigation_after_close_does_not_raise(self):
        dialog = UploadSessionDialog(
            SimpleNamespace(
                id=1,
                full_name="Test Missionary",
                current_stage="GENERAL",
            )
        )
        dialog.ocr_checkbox.setChecked(False)
        dialog.add_files(["a.pdf", "b.pdf"])
        dialog.accept()

        dialog.go_to_next_item()
        dialog.persist_current_item_state()
        dialog.load_detail()
        dialog.render_ocr_fields(dialog.controller.items[0])

    def test_upload_session_fallback_uses_backdrop_snapshot(self):
        self.assertFalse(FLUENT_DIALOG_AVAILABLE)

        window = MainWindow()
        window.resize(1400, 900)
        window.show()
        self.app.processEvents()

        detail = window.detail_page
        missionary = SimpleNamespace(
            id=1,
            full_name="Test Missionary",
            current_stage="GENERAL",
        )
        dialog = UploadSessionDialog(
            missionary,
            parent=detail,
        )

        dialog.show()
        self.app.processEvents()

        self.assertIsNone(detail.graphicsEffect())
        self.assertIsNotNone(dialog._backdrop_label)
        self.assertIsNotNone(dialog._backdrop_scrim)
        self.assertFalse(dialog._backdrop_label.pixmap().isNull())
        self.assertEqual(
            dialog._surface_host.objectName(),
            "UploadWorkspaceSurface",
        )
        self.assertTrue(dialog._surface_host.isVisible())
        self.assertTrue(dialog.isModal())

        dialog.close()
        window.close()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
