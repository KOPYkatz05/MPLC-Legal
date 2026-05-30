import tempfile

from datetime import date

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QFormLayout,
)

from PySide6.QtCore import Qt

from services.workflow_service import (
    WorkflowService,
)

from services.document_service import (
    DocumentService,
)

from services.missionary_service import (
    MissionaryService,
)

from services.ocr_service import (
    OCRService,
)

from services.document_parser import (
    DocumentParser,
)

from services.document_image_export_service import (
    DocumentImageExportService,
)

from ui.dialogs.upload_document_dialog import (
    UploadDocumentDialog,
)

from ui.dialogs.document_editor_dialog import (
    DocumentEditorDialog,
)

from ui.dialogs.ocr_review_dialog import (
    OCRReviewDialog,
)

from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STATUSES,
)

from utils.logger import logger

from services.workflow_validator import (
    WorkflowValidator,
)


# ==========================================
# Fields that require date parsing
# when writing back to the missionary record
# ==========================================

DATE_AUTO_UPDATE_FIELDS = {
    "arrival_date",
    "carnet_issue_date",
    "residency_expiration",
    "prorroga_expiration",
    "cancelacion_date",
}


class MissionaryDetailPage(QWidget):
    def __init__(
        self,
        main_window
    ):
        super().__init__()

        self.main_window = main_window

        logger.info(
            "Initializing MissionaryDetailPage"
        )

        self.workflow_service = (
            WorkflowService()
        )

        self.document_service = (
            DocumentService()
        )

        self.missionary_service = (
            MissionaryService()
        )

        self.ocr_service = None

        self.document_parser = (
            DocumentParser()
        )

        self.image_export_service = (
            DocumentImageExportService()
        )

        self.setup_ui()

        self.workflow_list.itemDoubleClicked.connect(
            self.change_workflow_status
        )

        self.workflow_validator = (
            WorkflowValidator()
        )

    def _get_ocr_service(self):
        if self.ocr_service is None:
            try:
                self.ocr_service = OCRService()

            except Exception:
                logger.exception(
                    "Failed to initialize OCR service"
                )

        return self.ocr_service

    def setup_ui(self):
        logger.debug(
            "Setting up MissionaryDetailPage UI"
        )

        main_layout = QVBoxLayout()

        self.setLayout(main_layout)

        # ==========================================
        # Tabs
        # ==========================================

        self.tabs = QTabWidget()

        main_layout.addWidget(
            self.tabs
        )

        # ==========================================
        # PROCESS OVERVIEW TAB
        # ==========================================

        self.process_tab = QWidget()

        self.tabs.addTab(
            self.process_tab,
            "Process Overview"
        )

        process_layout = QVBoxLayout()

        self.process_tab.setLayout(
            process_layout
        )

        # Name
        self.name_label = QLabel(
            "Name:"
        )

        process_layout.addWidget(
            self.name_label
        )

        # Current Stage
        self.stage_label = QLabel(
            "Current Stage:"
        )

        process_layout.addWidget(
            self.stage_label
        )

        # Workflow List
        process_layout.addWidget(
            QLabel("Workflow Stages")
        )

        self.workflow_list = QListWidget()

        process_layout.addWidget(
            self.workflow_list
        )

        # Documents
        process_layout.addWidget(
            QLabel("Documents")
        )

        self.upload_button = QPushButton(
            "Upload Document"
        )

        process_layout.addWidget(
            self.upload_button
        )

        self.documents_list = QListWidget()

        process_layout.addWidget(
            self.documents_list
        )

        process_layout.addWidget(
            QLabel("Missing Documents")
        )

        self.missing_documents_list = (
            QListWidget()
        )

        process_layout.addWidget(
            self.missing_documents_list
        )

        # Delete Button
        self.delete_button = QPushButton(
            "Delete Missionary"
        )

        process_layout.addWidget(
            self.delete_button
        )

        process_layout.addStretch()

        # ==========================================
        # DETAILS TAB
        # ==========================================

        self.details_tab = QWidget()

        self.tabs.addTab(
            self.details_tab,
            "Details"
        )

        details_layout = QFormLayout()

        self.details_tab.setLayout(
            details_layout
        )

        self.nationality_label = QLabel("-")
        self.passport_label = QLabel("-")
        self.folder_label = QLabel("-")
        self.arrival_date_label = QLabel("-")
        self.visa_expiration_label = QLabel("-")
        self.prorroga_expiration_label = QLabel("-")
        self.carnet_issue_date_label = QLabel("-")
        self.cancelacion_date_label = QLabel("-")

        details_layout.addRow(
            "Nationality:",
            self.nationality_label,
        )

        details_layout.addRow(
            "Passport Number:",
            self.passport_label,
        )

        details_layout.addRow(
            "Arrival Date:",
            self.arrival_date_label,
        )

        details_layout.addRow(
            "Visa Expiration:",
            self.visa_expiration_label,
        )

        details_layout.addRow(
            "Prórroga Expiration:",
            self.prorroga_expiration_label,
        )

        details_layout.addRow(
            "Carnet Issue Date:",
            self.carnet_issue_date_label,
        )

        details_layout.addRow(
            "Cancelación Date:",
            self.cancelacion_date_label,
        )

        details_layout.addRow(
            "Folder Path:",
            self.folder_label,
        )

        # ==========================================
        # Connections
        # ==========================================

        self.upload_button.clicked.connect(
            self.upload_document
        )

        self.delete_button.clicked.connect(
            self.delete_missionary
        )

        logger.debug(
            "MissionaryDetailPage UI setup complete"
        )

    # ==========================================
    # LOAD MISSIONARY
    # ==========================================

    def load_missing_documents(self):
        self.missing_documents_list.clear()

        workflows = (
            self.workflow_service
            .get_workflows(
                self.current_missionary.id
            )
        )

        for workflow in workflows:

            missing_documents = (
                self.workflow_validator
                .get_missing_documents(
                    self.current_missionary.id,
                    workflow.stage_name
                )
            )

            self.missing_documents_list.addItem(
                f"--- "
                f"{workflow.stage_name} "
                f"---"
            )

            if missing_documents:
                for document in missing_documents:
                    self.missing_documents_list.addItem(
                        f"Missing: {document}"
                    )
            else:
                self.missing_documents_list.addItem(
                    "All required documents uploaded."
                )

    def load_missionary(
        self,
        missionary
    ):
        self.current_missionary = missionary

        logger.info(
            f"Loading missionary details for "
            f"{missionary.full_name}"
        )

        self.name_label.setText(
            f"Name: {missionary.full_name}"
        )

        self.stage_label.setText(
            f"Current Stage: "
            f"{missionary.current_stage or ''}"
        )

        self.nationality_label.setText(
            missionary.nationality or "-"
        )

        self.passport_label.setText(
            missionary.passport_number or "-"
        )

        self.folder_label.setText(
            missionary.folder_path or "-"
        )

        self.arrival_date_label.setText(
            self.format_date(
                missionary.arrival_date
            )
        )

        self.visa_expiration_label.setText(
            self.format_date(
                missionary.visa_expiration
            )
        )

        self.prorroga_expiration_label.setText(
            self.format_date(
                missionary.prorroga_expiration
            )
        )

        self.carnet_issue_date_label.setText(
            self.format_date(
                missionary.carnet_issue_date
            )
        )

        self.cancelacion_date_label.setText(
            self.format_date(
                missionary.cancelacion_date
            )
        )

        self.workflow_list.clear()

        workflows = (
            self.workflow_service
            .get_workflows(
                missionary.id
            )
        )

        for workflow in workflows:
            item_text = (
                f"{workflow.stage_name} - "
                f"{workflow.status}"
            )

            item = QListWidgetItem(item_text)

            item.setData(
                Qt.UserRole,
                workflow.id,
            )

            self.workflow_list.addItem(item)

        self.load_documents()
        self.load_missing_documents()

    # ==========================================
    # WORKFLOW STATUS
    # ==========================================

    def change_workflow_status(
        self,
        item
    ):
        workflow_id = item.data(Qt.UserRole)

        selected_status, ok = (
            QInputDialog.getItem(
                self,
                "Change Status",
                "Select new status:",
                WORKFLOW_STATUSES,
                0,
                False,
            )
        )

        if not ok:
            return

        self.workflow_service.update_workflow_status(
            workflow_id,
            selected_status,
        )

        if hasattr(self, "current_missionary"):
            self.load_missionary(
                self.current_missionary
            )

    # ==========================================
    # UPLOAD DOCUMENT — full OCR pipeline
    # ==========================================

    def upload_document(self):
        if not hasattr(self, "current_missionary"):
            return

        missionary = self.current_missionary

        # ------------------------------------------
        # Step 1: Select file
        # ------------------------------------------

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document",
            "",
            "Documents (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif)",
        )

        if not file_path:
            return

        # ------------------------------------------
        # Step 2: Choose document type + stage
        # ------------------------------------------

        upload_dialog = UploadDocumentDialog(self)

        if upload_dialog.exec() != UploadDocumentDialog.Accepted:
            return

        document_type = upload_dialog.get_document_type()
        workflow_stage = upload_dialog.get_workflow_stage()

        # ------------------------------------------
        # Step 3: Document editor (crop / rotate)
        # ------------------------------------------

        editor = DocumentEditorDialog(
            file_path,
            parent=self,
        )

        if editor.exec() != DocumentEditorDialog.Accepted:
            return

        export_settings = editor.get_export_settings()

        # ------------------------------------------
        # Step 4: Export the processed image for OCR
        # ------------------------------------------

        ocr_image_path = self._export_for_ocr(
            file_path,
            export_settings,
        )

        # ------------------------------------------
        # Step 5 & 6: Run OCR + parse
        # ------------------------------------------

        ocr_fields = (
            DOCUMENTS
            .get(document_type, {})
            .get("ocr_fields", [])
        )

        parsed_data = {}

        if ocr_fields and ocr_image_path:
            parsed_data = self._run_ocr(
                ocr_image_path,
                document_type,
            )

        # ------------------------------------------
        # Step 7: Review dialog (if fields extracted)
        # ------------------------------------------

        confirmed_data = {}

        if ocr_fields:
            review_dialog = OCRReviewDialog(
                ocr_fields=ocr_fields,
                parsed_data=parsed_data,
                parent=self,
            )

            if review_dialog.exec() == OCRReviewDialog.Accepted:
                confirmed_data = review_dialog.get_data()

        # ------------------------------------------
        # Step 8: Save document to DB + filesystem
        # ------------------------------------------

        try:
            self.document_service.upload_document(
                missionary=missionary,
                source_file=file_path,
                document_type=document_type,
                workflow_stage=workflow_stage,
            )

            logger.info(
                f"Saved document {document_type} "
                f"for {missionary.full_name}"
            )

        except Exception:
            logger.exception(
                "Failed to save document"
            )

            QMessageBox.critical(
                self,
                "Upload Failed",
                "The document could not be saved. "
                "Check the logs for details.",
            )

            return

        # ------------------------------------------
        # Step 9: Apply auto_updates to missionary
        # ------------------------------------------

        if confirmed_data:
            auto_update_fields = (
                DOCUMENTS
                .get(document_type, {})
                .get("auto_updates", [])
            )

            self._apply_auto_updates(
                missionary.id,
                confirmed_data,
                auto_update_fields,
            )

        # ------------------------------------------
        # Step 10: Refresh UI
        # ------------------------------------------

        # Reload missionary to pick up any updated fields
        from database.db import SessionLocal
        from database.models.missionary import Missionary as MissionaryModel

        session = SessionLocal()

        try:
            refreshed = (
                session.query(MissionaryModel)
                .filter_by(id=missionary.id)
                .first()
            )

            if refreshed:
                self.load_missionary(refreshed)

        finally:
            session.close()

    # ==========================================
    # OCR HELPERS
    # ==========================================

    def _export_for_ocr(
        self,
        file_path,
        export_settings,
    ):
        file_path = Path(file_path)

        suffix = file_path.suffix.lower()

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False,
        )

        tmp_path = Path(tmp.name)

        tmp.close()

        try:
            if suffix == ".pdf":
                self.image_export_service.export_pdf_page(
                    pdf_path=file_path,
                    page_index=export_settings.get("page", 0),
                    rotation_angle=export_settings.get("rotation", 0),
                    crop_rect=export_settings.get("crop_rect"),
                    output_path=str(tmp_path),
                )

            else:
                from PIL import Image

                img = Image.open(str(file_path))

                rotation = export_settings.get("rotation", 0)

                if rotation:
                    img = img.rotate(
                        -rotation,
                        expand=True,
                    )

                crop_rect = export_settings.get("crop_rect")

                if crop_rect:
                    img = img.crop((
                        int(crop_rect.left()),
                        int(crop_rect.top()),
                        int(crop_rect.right()),
                        int(crop_rect.bottom()),
                    ))

                img.save(str(tmp_path))

            return tmp_path

        except Exception:
            logger.exception(
                "Failed to export document image for OCR"
            )

            return None

    def _run_ocr(
        self,
        image_path,
        document_type,
    ):
        try:
            ocr = self._get_ocr_service()

            if ocr is None:
                logger.warning(
                    "OCR service unavailable, skipping"
                )

                return {}

            raw_text = ocr.extract_text(
                str(image_path)
            )

            parsed = self.document_parser.parse(
                raw_text,
                document_type,
            )

            logger.info(
                f"OCR parsed fields: "
                f"{list(parsed.keys())}"
            )

            return parsed

        except Exception:
            logger.exception(
                f"OCR failed for {document_type}"
            )

            return {}

    def _apply_auto_updates(
        self,
        missionary_id,
        confirmed_data,
        auto_update_fields,
    ):
        updates = {}

        for field in auto_update_fields:
            value_str = confirmed_data.get(field, "")

            if not value_str:
                continue

            if field in DATE_AUTO_UPDATE_FIELDS:
                parsed_date = self._parse_date(
                    value_str
                )

                if parsed_date:
                    updates[field] = parsed_date

            else:
                updates[field] = value_str

        if updates:
            try:
                self.missionary_service.update_fields(
                    missionary_id,
                    updates,
                )

                logger.info(
                    f"Auto-updated missionary fields: "
                    f"{list(updates.keys())}"
                )

            except Exception:
                logger.exception(
                    "Failed to apply auto-updates "
                    "to missionary"
                )

    def _parse_date(self, value_str):
        if not value_str:
            return None

        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d-%m-%Y",
        ]

        from datetime import datetime

        for fmt in formats:
            try:
                return datetime.strptime(
                    value_str.strip(),
                    fmt,
                ).date()

            except ValueError:
                continue

        logger.warning(
            f"Could not parse date string: '{value_str}'"
        )

        return None

    # ==========================================
    # DOCUMENTS LIST
    # ==========================================

    def load_documents(self):
        self.documents_list.clear()

        documents = (
            self.document_service
            .get_documents(
                self.current_missionary.id
            )
        )

        for document in documents:
            doc_config = DOCUMENTS.get(
                document.document_type,
                {},
            )

            label = doc_config.get(
                "label",
                document.document_type,
            )

            self.documents_list.addItem(
                f"{label} — {document.file_name}"
            )

    # ==========================================
    # DELETE MISSIONARY
    # ==========================================

    def delete_missionary(self):
        if not hasattr(self, "current_missionary"):
            return

        response = QMessageBox.question(
            self,
            "Confirm Delete",
            (
                "Are you sure you want to "
                "delete this missionary?\n\n"
                "This will move the missionary "
                "to the TRASH PILE."
            ),
            QMessageBox.Yes | QMessageBox.No,
        )

        if response != QMessageBox.Yes:
            return

        self.missionary_service.delete_missionary(
            self.current_missionary.id
        )

        missionaries_page = (
            self.main_window.stack.widget(1)
        )

        missionaries_page.load_data()

        self.main_window.stack.setCurrentIndex(1)

    # ==========================================
    # HELPERS
    # ==========================================

    def format_date(self, date_value):
        if not date_value:
            return "-"

        return date_value.strftime("%B %d, %Y")
