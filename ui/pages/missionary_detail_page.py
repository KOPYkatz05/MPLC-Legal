import tempfile

from datetime import date

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QFormLayout,
    QFrame,
    QScrollArea,
    QTextEdit,
    QMenu,
    QSizePolicy,
)

from PySide6.QtCore import Qt, QSize

from PySide6.QtGui import QIcon, QColor

from services.workflow_service import WorkflowService

from services.document_service import DocumentService

from services.missionary_service import MissionaryService

from services.ocr_service import OCRService

from services.document_parser import DocumentParser

from services.document_image_export_service import (
    DocumentImageExportService,
)

from services.thumbnail_service import ThumbnailService

from ui.dialogs.upload_document_dialog import (
    UploadDocumentDialog,
)

from ui.dialogs.document_editor_dialog import (
    DocumentEditorDialog,
)

from ui.dialogs.ocr_review_dialog import OCRReviewDialog

from ui.dialogs.stage_advance_dialog import (
    StageAdvanceDialog,
)

from ui.dialogs.batch_upload_dialog import (
    BatchUploadDialog,
)

from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STATUSES,
    WORKFLOW_STAGES,
)

from utils.logger import logger

from services.workflow_validator import WorkflowValidator


DATE_AUTO_UPDATE_FIELDS = {
    "arrival_date",
    "carnet_issue_date",
    "residency_expiration",
    "prorroga_expiration",
    "cancelacion_date",
}


class MissionaryDetailPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("MissionaryDetailPage")

        self.main_window = main_window

        logger.info("Initializing MissionaryDetailPage")

        self.workflow_service = WorkflowService()

        self.document_service = DocumentService()

        self.missionary_service = MissionaryService()

        self.workflow_validator = WorkflowValidator()

        self.thumb_service = ThumbnailService()

        self.ocr_service = None

        self.document_parser = DocumentParser()

        self.image_export_service = (
            DocumentImageExportService()
        )

        self._document_data = []

        self.setup_ui()

    def _get_ocr_service(self):
        if self.ocr_service is None:
            try:
                self.ocr_service = OCRService()
            except Exception:
                logger.exception(
                    "Failed to initialize OCR service"
                )
        return self.ocr_service

    # ==========================================
    # UI SETUP
    # ==========================================

    def setup_ui(self):
        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(0, 0, 0, 0)

        main_layout.setSpacing(0)

        self.setLayout(main_layout)

        # ==========================================
        # Page Header
        # ==========================================

        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            32, 18, 32, 18
        )

        header_layout.setSpacing(12)

        header.setLayout(header_layout)

        # Name + stage in a vertical stack
        name_stage = QVBoxLayout()

        name_stage.setSpacing(4)

        self.name_label = QLabel("—")

        self.name_label.setObjectName("PageTitle")

        self.stage_badge = QLabel("")

        self.stage_badge.setObjectName("StageBadge")

        self.stage_badge.setStyleSheet(
            "background-color: #EFF6FF; "
            "color: #1D4ED8; "
            "font-size: 11px; "
            "font-weight: 600; "
            "padding: 2px 10px; "
            "border-radius: 10px; "
            "border: 1px solid #BFDBFE; "
            "background: transparent;"
        )

        name_stage.addWidget(self.name_label)

        name_stage.addWidget(
            self.stage_badge,
            alignment=Qt.AlignLeft,
        )

        header_layout.addLayout(name_stage)

        header_layout.addStretch()

        self.advance_button = QPushButton(
            "→ Advance Stage"
        )

        self.advance_button.setObjectName(
            "AdvanceButton"
        )

        self.advance_button.setFixedHeight(34)

        self.advance_button.setStyleSheet(
            "QPushButton#AdvanceButton {"
            "background-color: #059669; "
            "color: white; "
            "border: none; "
            "border-radius: 6px; "
            "padding: 0px 16px; "
            "font-weight: 500; "
            "font-size: 13px;"
            "}"
            "QPushButton#AdvanceButton:hover {"
            "background-color: #047857;"
            "}"
        )

        self.advance_button.clicked.connect(
            self._advance_stage
        )

        self.delete_button = QPushButton(
            "Delete Missionary"
        )

        self.delete_button.setFixedHeight(34)

        self.delete_button.clicked.connect(
            self.delete_missionary
        )

        header_layout.addWidget(self.advance_button)

        header_layout.addWidget(self.delete_button)

        main_layout.addWidget(header)

        # Header divider
        hdr_div = QFrame()

        hdr_div.setObjectName("HeaderDivider")

        hdr_div.setFixedHeight(1)

        main_layout.addWidget(hdr_div)

        # ==========================================
        # Auto-advance banner (hidden by default)
        # ==========================================

        self.advance_banner = QFrame()

        self.advance_banner.setObjectName(
            "AdvanceBanner"
        )

        self.advance_banner.setStyleSheet(
            "QFrame#AdvanceBanner {"
            "background-color: #DCFCE7; "
            "border-bottom: 1px solid #86EFAC;"
            "}"
        )

        self.advance_banner.setVisible(False)

        banner_layout = QHBoxLayout()

        banner_layout.setContentsMargins(
            32, 10, 32, 10
        )

        banner_layout.setSpacing(12)

        self.advance_banner.setLayout(
            banner_layout
        )

        banner_icon = QLabel("✓")

        banner_icon.setStyleSheet(
            "color: #059669; "
            "font-size: 16px; "
            "font-weight: 700; "
            "background: transparent;"
        )

        self.banner_text = QLabel(
            "All required documents uploaded — "
            "ready to advance to the next stage."
        )

        self.banner_text.setStyleSheet(
            "color: #166534; "
            "font-size: 13px; "
            "background: transparent;"
        )

        banner_now_btn = QPushButton(
            "Advance Now"
        )

        banner_now_btn.setStyleSheet(
            "QPushButton {"
            "background-color: #059669; "
            "color: white; "
            "border: none; "
            "border-radius: 6px; "
            "padding: 4px 14px; "
            "font-size: 12px; "
            "font-weight: 500;"
            "}"
            "QPushButton:hover {"
            "background-color: #047857;"
            "}"
        )

        banner_now_btn.clicked.connect(
            self._advance_stage
        )

        banner_layout.addWidget(banner_icon)

        banner_layout.addWidget(self.banner_text)

        banner_layout.addStretch()

        banner_layout.addWidget(banner_now_btn)

        main_layout.addWidget(self.advance_banner)

        # ==========================================
        # Tabs
        # ==========================================

        self.tabs = QTabWidget()

        main_layout.addWidget(
            self.tabs, stretch=1
        )

        self._build_overview_tab()

        self._build_details_tab()

        self._build_notes_tab()

        # Connections
        self.workflow_list.itemDoubleClicked.connect(
            self.change_workflow_status
        )

    def _build_overview_tab(self):
        overview_tab = QWidget()

        self.tabs.addTab(overview_tab, "Overview")

        tab_layout = QVBoxLayout()

        tab_layout.setContentsMargins(0, 0, 0, 0)

        overview_tab.setLayout(tab_layout)

        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()

        content.setStyleSheet(
            "background-color: #F4F4F5;"
        )

        content_layout = QVBoxLayout()

        content_layout.setContentsMargins(
            32, 24, 32, 24
        )

        content_layout.setSpacing(20)

        content.setLayout(content_layout)

        # ---- Workflow section ----
        wf_section_hdr = QLabel("Workflow Stages")

        wf_section_hdr.setObjectName("SectionHeader")

        content_layout.addWidget(wf_section_hdr)

        self.workflow_list = QListWidget()

        self.workflow_list.setMaximumHeight(160)

        content_layout.addWidget(self.workflow_list)

        # ---- Documents section ----
        docs_hdr_row = QHBoxLayout()

        docs_label = QLabel("Documents")

        docs_label.setObjectName("SectionHeader")

        self.batch_upload_btn = QPushButton(
            "⬆  Batch Upload"
        )

        self.batch_upload_btn.setFixedHeight(30)

        self.batch_upload_btn.clicked.connect(
            self._batch_upload
        )

        self.upload_button = QPushButton(
            "Upload Document"
        )

        self.upload_button.setObjectName(
            "PrimaryButton"
        )

        self.upload_button.setFixedHeight(30)

        self.upload_button.clicked.connect(
            self.upload_document
        )

        docs_hdr_row.addWidget(docs_label)

        docs_hdr_row.addStretch()

        docs_hdr_row.addWidget(self.batch_upload_btn)

        docs_hdr_row.addWidget(self.upload_button)

        content_layout.addLayout(docs_hdr_row)

        self.documents_list = QListWidget()

        self.documents_list.setIconSize(
            QSize(60, 75)
        )

        self.documents_list.setSpacing(2)

        self.documents_list.setMinimumHeight(200)

        self.documents_list.setContextMenuPolicy(
            Qt.CustomContextMenu
        )

        self.documents_list.customContextMenuRequested.connect(
            self._show_doc_context_menu
        )

        content_layout.addWidget(
            self.documents_list
        )

        # ---- Missing documents section ----
        missing_label = QLabel("Missing Documents")

        missing_label.setObjectName("SectionHeader")

        content_layout.addWidget(missing_label)

        self.missing_documents_list = QListWidget()

        self.missing_documents_list.setMaximumHeight(
            160
        )

        content_layout.addWidget(
            self.missing_documents_list
        )

        content_layout.addStretch()

        scroll.setWidget(content)

        tab_layout.addWidget(scroll)

    def _build_details_tab(self):
        details_outer = QWidget()

        self.tabs.addTab(details_outer, "Details")

        outer_layout = QVBoxLayout()

        outer_layout.setContentsMargins(0, 0, 0, 0)

        details_outer.setLayout(outer_layout)

        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setFrameShape(QFrame.NoFrame)

        details_content = QWidget()

        details_content.setStyleSheet(
            "background-color: #F4F4F5;"
        )

        details_layout = QVBoxLayout()

        details_layout.setContentsMargins(
            32, 24, 32, 24
        )

        details_layout.setSpacing(0)

        details_content.setLayout(details_layout)

        card = QFrame()

        card.setObjectName("StatCard")

        card.setStyleSheet(
            "QFrame#StatCard {"
            "background-color: white; "
            "border: 1px solid #E4E4E7; "
            "border-radius: 10px;"
            "}"
        )

        form = QFormLayout()

        form.setContentsMargins(24, 20, 24, 20)

        form.setSpacing(14)

        form.setLabelAlignment(Qt.AlignRight)

        card.setLayout(form)

        def make_field():
            lbl = QLabel("-")
            lbl.setStyleSheet(
                "color: #18181B; "
                "font-size: 13px; "
                "background: transparent;"
            )
            return lbl

        def row_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color: #71717A; "
                "font-size: 12px; "
                "background: transparent;"
            )
            return lbl

        self.nationality_label = make_field()
        self.passport_label = make_field()
        self.arrival_date_label = make_field()
        self.visa_expiration_label = make_field()
        self.residency_exp_label = make_field()
        self.prorroga_expiration_label = make_field()
        self.carnet_issue_date_label = make_field()
        self.cancelacion_date_label = make_field()
        self.folder_label = make_field()

        self.folder_label.setWordWrap(True)

        form.addRow(
            row_label("Nationality:"),
            self.nationality_label,
        )

        form.addRow(
            row_label("Passport Number:"),
            self.passport_label,
        )

        form.addRow(
            row_label("Arrival Date:"),
            self.arrival_date_label,
        )

        form.addRow(
            row_label("Visa Expiration:"),
            self.visa_expiration_label,
        )

        form.addRow(
            row_label("Residency Expiration:"),
            self.residency_exp_label,
        )

        form.addRow(
            row_label("Prórroga Expiration:"),
            self.prorroga_expiration_label,
        )

        form.addRow(
            row_label("Carnet Issue Date:"),
            self.carnet_issue_date_label,
        )

        form.addRow(
            row_label("Cancelación Date:"),
            self.cancelacion_date_label,
        )

        form.addRow(
            row_label("Folder Path:"),
            self.folder_label,
        )

        details_layout.addWidget(card)

        details_layout.addStretch()

        scroll.setWidget(details_content)

        outer_layout.addWidget(scroll)

    def _build_notes_tab(self):
        notes_tab = QWidget()

        self.tabs.addTab(notes_tab, "Notes")

        notes_layout = QVBoxLayout()

        notes_layout.setContentsMargins(
            32, 24, 32, 24
        )

        notes_layout.setSpacing(12)

        notes_tab.setLayout(notes_layout)

        notes_tab.setStyleSheet(
            "background-color: #F4F4F5;"
        )

        hint = QLabel(
            "Use this space to record status "
            "updates, reminders, or any notes "
            "about this missionary's legal process."
        )

        hint.setStyleSheet(
            "color: #71717A; "
            "font-size: 12px; "
            "background: transparent;"
        )

        hint.setWordWrap(True)

        notes_layout.addWidget(hint)

        self.notes_text = QTextEdit()

        self.notes_text.setPlaceholderText(
            "Enter notes here..."
        )

        self.notes_text.setStyleSheet(
            "QTextEdit {"
            "background-color: white; "
            "border: 1px solid #D4D4D8; "
            "border-radius: 8px; "
            "padding: 12px; "
            "font-size: 13px; "
            "color: #18181B;"
            "}"
            "QTextEdit:focus {"
            "border-color: #3B82F6;"
            "}"
        )

        notes_layout.addWidget(
            self.notes_text, stretch=1
        )

        save_notes_btn = QPushButton("Save Notes")

        save_notes_btn.setObjectName("PrimaryButton")

        save_notes_btn.setFixedHeight(34)

        save_notes_btn.setFixedWidth(140)

        save_notes_btn.clicked.connect(
            self._save_notes
        )

        notes_layout.addWidget(
            save_notes_btn,
            alignment=Qt.AlignRight,
        )

    # ==========================================
    # LOAD MISSIONARY
    # ==========================================

    def load_missionary(self, missionary):
        self.current_missionary = missionary

        logger.info(
            f"Loading missionary details for "
            f"{missionary.full_name}"
        )

        # Header
        self.name_label.setText(missionary.full_name)

        stage = missionary.current_stage or "—"

        self.stage_badge.setText(f"  {stage}  ")

        # Details tab
        self.nationality_label.setText(
            missionary.nationality or "-"
        )

        self.passport_label.setText(
            missionary.passport_number or "-"
        )

        self.arrival_date_label.setText(
            self.format_date(missionary.arrival_date)
        )

        self.visa_expiration_label.setText(
            self.format_date(
                missionary.visa_expiration
            )
        )

        self.residency_exp_label.setText(
            self.format_date(
                getattr(
                    missionary,
                    "residency_expiration",
                    None,
                )
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

        self.folder_label.setText(
            missionary.folder_path or "-"
        )

        # Notes tab
        self.notes_text.setPlainText(
            missionary.notes or ""
        )

        # Workflow list
        self.workflow_list.clear()

        workflows = self.workflow_service.get_workflows(
            missionary.id
        )

        for wf in workflows:
            item_text = (
                f"{wf.stage_name}  —  {wf.status}"
            )

            item = QListWidgetItem(item_text)

            item.setData(Qt.UserRole, wf.id)

            if wf.status == "COMPLETED":
                item.setForeground(
                    QColor("#059669")
                )

            elif wf.status == "WAITING":
                item.setForeground(
                    QColor("#D97706")
                )

            elif wf.status == "BLOCKED":
                item.setForeground(
                    QColor("#DC2626")
                )

            self.workflow_list.addItem(item)

        self.load_documents()

        self.load_missing_documents()

        self._update_advance_banner()

    def _update_advance_banner(self):
        if not hasattr(self, "current_missionary"):
            self.advance_banner.setVisible(False)
            return

        stage = (
            self.current_missionary.current_stage
        )

        if not stage:
            self.advance_banner.setVisible(False)
            return

        missing = (
            self.workflow_validator
            .get_missing_documents(
                self.current_missionary.id, stage
            )
        )

        if not missing:
            # Determine next stage label
            if stage in WORKFLOW_STAGES:
                idx = WORKFLOW_STAGES.index(stage)

                next_stage = (
                    WORKFLOW_STAGES[idx + 1]
                    if idx + 1 < len(WORKFLOW_STAGES)
                    else None
                )

            else:
                next_stage = None

            if next_stage:
                msg = (
                    f"All required documents for "
                    f"{stage} are uploaded — "
                    f"ready to advance to "
                    f"{next_stage}."
                )

            else:
                msg = (
                    f"All required documents for "
                    f"{stage} are uploaded."
                )

            self.banner_text.setText(msg)

            self.advance_banner.setVisible(True)

        else:
            self.advance_banner.setVisible(False)

    # ==========================================
    # WORKFLOW STATUS
    # ==========================================

    def change_workflow_status(self, item):
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
            workflow_id, selected_status
        )

        if hasattr(self, "current_missionary"):
            self._reload_missionary()

    # ==========================================
    # ADVANCE STAGE
    # ==========================================

    def _advance_stage(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = StageAdvanceDialog(
            self.current_missionary, parent=self
        )

        if dialog.exec() == StageAdvanceDialog.Accepted:
            self._reload_missionary()

            # Refresh missionaries list too
            missionaries_page = (
                self.main_window.stack.widget(1)
            )

            if missionaries_page:
                missionaries_page.load_data()

    # ==========================================
    # UPLOAD DOCUMENT — full OCR pipeline
    # ==========================================

    def upload_document(self):
        if not hasattr(self, "current_missionary"):
            return

        missionary = self.current_missionary

        # Step 1: Select file
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document",
            "",
            "Documents ("
            "*.pdf *.png *.jpg *.jpeg "
            "*.bmp *.tiff *.tif"
            ")",
        )

        if not file_path:
            return

        # Step 2: Choose document type + stage
        upload_dialog = UploadDocumentDialog(self)

        if (
            upload_dialog.exec()
            != UploadDocumentDialog.Accepted
        ):
            return

        document_type = upload_dialog.get_document_type()

        workflow_stage = upload_dialog.get_workflow_stage()

        # Step 3: Duplicate detection
        if self.document_service.document_type_exists(
            missionary.id, document_type
        ):
            doc_label = (
                DOCUMENTS.get(document_type, {})
                .get("label", document_type)
            )

            response = QMessageBox.question(
                self,
                "Document Already Exists",
                f"A '{doc_label}' has already been "
                f"uploaded for this missionary.\n\n"
                f"Replace it with the new file?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if response == QMessageBox.No:
                return

            self.document_service.delete_document_by_type(
                missionary.id, document_type
            )

        # Step 4: Document editor (crop / rotate)
        editor = DocumentEditorDialog(
            file_path, parent=self
        )

        if editor.exec() != DocumentEditorDialog.Accepted:
            return

        export_settings = editor.get_export_settings()

        # Step 5: Export the processed image for OCR
        ocr_image_path = self._export_for_ocr(
            file_path, export_settings
        )

        # Step 6 & 7: Run OCR + parse
        ocr_fields = (
            DOCUMENTS.get(document_type, {})
            .get("ocr_fields", [])
        )

        parsed_data = {}

        if ocr_fields and ocr_image_path:
            parsed_data = self._run_ocr(
                ocr_image_path, document_type
            )

        # Step 8: Review dialog
        confirmed_data = {}

        if ocr_fields:
            review_dialog = OCRReviewDialog(
                ocr_fields=ocr_fields,
                parsed_data=parsed_data,
                parent=self,
            )

            if (
                review_dialog.exec()
                == OCRReviewDialog.Accepted
            ):
                confirmed_data = (
                    review_dialog.get_data()
                )

        # Step 9: Save document to DB + filesystem
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

        # Step 10: Apply auto_updates to missionary
        if confirmed_data:
            auto_update_fields = (
                DOCUMENTS.get(document_type, {})
                .get("auto_updates", [])
            )

            self._apply_auto_updates(
                missionary.id,
                confirmed_data,
                auto_update_fields,
            )

        # Step 11: Refresh UI
        self._reload_missionary()

    # ==========================================
    # BATCH UPLOAD
    # ==========================================

    def _batch_upload(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = BatchUploadDialog(
            self.current_missionary, parent=self
        )

        dialog.exec()

        self._reload_missionary()

    # ==========================================
    # OCR HELPERS
    # ==========================================

    def _export_for_ocr(
        self, file_path, export_settings
    ):
        file_path = Path(file_path)

        suffix = file_path.suffix.lower()

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False
        )

        tmp_path = Path(tmp.name)

        tmp.close()

        try:
            if suffix == ".pdf":
                self.image_export_service.export_pdf_page(
                    pdf_path=file_path,
                    page_index=export_settings.get(
                        "page", 0
                    ),
                    rotation_angle=export_settings.get(
                        "rotation", 0
                    ),
                    crop_rect=export_settings.get(
                        "crop_rect"
                    ),
                    output_path=str(tmp_path),
                )

            else:
                from PIL import Image

                img = Image.open(str(file_path))

                rotation = export_settings.get(
                    "rotation", 0
                )

                if rotation:
                    img = img.rotate(
                        -rotation, expand=True
                    )

                crop_rect = export_settings.get(
                    "crop_rect"
                )

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
                "Failed to export document image "
                "for OCR"
            )

            return None

    def _run_ocr(self, image_path, document_type):
        try:
            ocr = self._get_ocr_service()

            if ocr is None:
                return {}

            raw_text = ocr.extract_text(
                str(image_path)
            )

            parsed = self.document_parser.parse(
                raw_text, document_type
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
                    missionary_id, updates
                )

                logger.info(
                    f"Auto-updated missionary fields: "
                    f"{list(updates.keys())}"
                )

            except Exception:
                logger.exception(
                    "Failed to apply auto-updates"
                )

    def _parse_date(self, value_str):
        if not value_str:
            return None

        from datetime import datetime

        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d-%m-%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(
                    value_str.strip(), fmt
                ).date()

            except ValueError:
                continue

        return None

    # ==========================================
    # DOCUMENTS LIST WITH THUMBNAILS
    # ==========================================

    def load_documents(self):
        self.documents_list.clear()

        self._document_data = []

        documents = self.document_service.get_documents(
            self.current_missionary.id
        )

        if not documents:
            empty = QListWidgetItem(
                "No documents uploaded yet."
            )

            empty.setForeground(QColor("#A1A1AA"))

            empty.setFlags(
                empty.flags() & ~Qt.ItemIsSelectable
            )

            self.documents_list.addItem(empty)

            return

        for doc in documents:
            doc_config = DOCUMENTS.get(
                doc.document_type, {}
            )

            label = doc_config.get(
                "label", doc.document_type
            )

            item_text = (
                f"{label}\n{doc.file_name}"
            )

            item = QListWidgetItem(item_text)

            item.setData(Qt.UserRole, doc.id)

            # Try thumbnail
            try:
                pixmap = self.thumb_service.get_pixmap(
                    doc.file_path
                )

                if pixmap and not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))

            except Exception:
                pass

            self.documents_list.addItem(item)

            self._document_data.append({
                "id": doc.id,
                "document_type": doc.document_type,
                "label": label,
                "file_path": doc.file_path,
                "file_name": doc.file_name,
                "notes": doc.notes or "",
            })

    def _show_doc_context_menu(self, pos):
        item = self.documents_list.itemAt(pos)

        if not item:
            return

        doc_id = item.data(Qt.UserRole)

        if doc_id is None:
            return

        menu = QMenu(self)

        notes_action = menu.addAction(
            "View / Edit Notes"
        )

        open_action = menu.addAction("Open File")

        action = menu.exec(
            self.documents_list.mapToGlobal(pos)
        )

        if action == notes_action:
            self._open_document_notes(doc_id)

        elif action == open_action:
            self._open_document_file(doc_id)

    def _find_doc_data(self, doc_id):
        return next(
            (
                d
                for d in self._document_data
                if d["id"] == doc_id
            ),
            None,
        )

    def _open_document_notes(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        dialog = QDialog_Notes(
            doc, self.document_service, parent=self
        )

        if dialog.exec():
            # Refresh so updated notes appear
            doc["notes"] = dialog.get_notes()

    def _open_document_file(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        try:
            import subprocess

            file_path = doc["file_path"]

            if not Path(file_path).exists():
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"Cannot open file:\n{file_path}",
                )

                return

            subprocess.Popen(
                ["xdg-open", file_path]
            )

        except Exception:
            logger.exception("Failed to open file")

    # ==========================================
    # MISSING DOCUMENTS
    # ==========================================

    def load_missing_documents(self):
        self.missing_documents_list.clear()

        workflows = self.workflow_service.get_workflows(
            self.current_missionary.id
        )

        any_missing = False

        for wf in workflows:
            missing = (
                self.workflow_validator
                .get_missing_documents(
                    self.current_missionary.id,
                    wf.stage_name,
                )
            )

            if not missing:
                continue

            any_missing = True

            stage_item = QListWidgetItem(
                f"— {wf.stage_name} —"
            )

            stage_item.setForeground(
                QColor("#A1A1AA")
            )

            stage_item.setFlags(
                stage_item.flags()
                & ~Qt.ItemIsSelectable
            )

            self.missing_documents_list.addItem(
                stage_item
            )

            for doc_key in missing:
                label = (
                    DOCUMENTS.get(doc_key, {})
                    .get("label", doc_key)
                )

                item = QListWidgetItem(
                    f"  ✗  {label}"
                )

                item.setForeground(QColor("#DC2626"))

                self.missing_documents_list.addItem(
                    item
                )

        if not any_missing:
            all_good = QListWidgetItem(
                "✓  All required documents uploaded."
            )

            all_good.setForeground(
                QColor("#059669")
            )

            all_good.setFlags(
                all_good.flags()
                & ~Qt.ItemIsSelectable
            )

            self.missing_documents_list.addItem(
                all_good
            )

    # ==========================================
    # NOTES
    # ==========================================

    def _save_notes(self):
        if not hasattr(self, "current_missionary"):
            return

        notes = self.notes_text.toPlainText()

        try:
            self.missionary_service.update_fields(
                self.current_missionary.id,
                {"notes": notes},
            )

            logger.info(
                f"Saved notes for "
                f"{self.current_missionary.full_name}"
            )

            QMessageBox.information(
                self,
                "Saved",
                "Notes saved successfully.",
            )

        except Exception:
            logger.exception(
                "Failed to save notes"
            )

            QMessageBox.critical(
                self,
                "Error",
                "Failed to save notes.",
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
            "Are you sure you want to delete "
            "this missionary?\n\n"
            "The missionary will be moved to "
            "the TRASH PILE.",
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

    def _reload_missionary(self):
        from database.db import SessionLocal
        from database.models.missionary import (
            Missionary as MissionaryModel,
        )

        session = SessionLocal()

        try:
            refreshed = (
                session.query(MissionaryModel)
                .filter_by(
                    id=self.current_missionary.id
                )
                .first()
            )

            if refreshed:
                self.load_missionary(refreshed)

        finally:
            session.close()

    def format_date(self, date_value):
        if not date_value:
            return "-"

        return date_value.strftime("%B %d, %Y")


# ==========================================
# Document Notes Dialog (inline)
# ==========================================

from PySide6.QtWidgets import QDialog


class QDialog_Notes(QDialog):
    def __init__(self, doc_data, doc_service, parent=None):
        super().__init__(parent)

        self.doc_data = doc_data

        self.doc_service = doc_service

        self.setWindowTitle(
            f"Notes — {doc_data['label']}"
        )

        self.setMinimumWidth(460)

        self.setMinimumHeight(320)

        layout = QVBoxLayout()

        layout.setContentsMargins(20, 20, 20, 16)

        layout.setSpacing(12)

        self.setLayout(layout)

        file_label = QLabel(
            f"File: {doc_data['file_name']}"
        )

        file_label.setStyleSheet(
            "color: #71717A; "
            "font-size: 12px;"
        )

        layout.addWidget(file_label)

        self.text_edit = QTextEdit()

        self.text_edit.setPlainText(
            doc_data.get("notes", "")
        )

        self.text_edit.setPlaceholderText(
            "Enter notes for this document..."
        )

        self.text_edit.setStyleSheet(
            "QTextEdit {"
            "background-color: white; "
            "border: 1px solid #D4D4D8; "
            "border-radius: 6px; "
            "padding: 8px; "
            "font-size: 13px;"
            "}"
        )

        layout.addWidget(self.text_edit, stretch=1)

        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")

        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Save Notes")

        save_btn.setObjectName("PrimaryButton")

        save_btn.setFixedHeight(34)

        save_btn.clicked.connect(self._save)

        btn_row.addStretch()

        btn_row.addWidget(cancel_btn)

        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _save(self):
        notes = self.text_edit.toPlainText()

        try:
            self.doc_service.update_document_notes(
                self.doc_data["id"], notes
            )

        except Exception:
            pass

        self.accept()

    def get_notes(self):
        return self.text_edit.toPlainText()
