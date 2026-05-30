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

from utils.constants import (
    DOCUMENT_TYPES,
    WORKFLOW_STATUSES,
)

from utils.logger import logger

from services.workflow_validator import (
    WorkflowValidator,
)


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

        self.setup_ui()

        self.workflow_list.itemDoubleClicked.connect(
            self.change_workflow_status
        )

        self.workflow_validator = (
            WorkflowValidator()
        )

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

        self.nationality_label = QLabel(
            "-"
        )

        self.passport_label = QLabel(
            "-"
        )

        self.folder_label = QLabel(
            "-"
        )

        self.arrival_date_label = QLabel(
            "-"
        )

        self.visa_expiration_label = QLabel(
            "-"
        )

        self.prorroga_expiration_label = QLabel(
            "-"
        )

        self.carnet_issue_date_label = QLabel(
            "-"
        )

        self.cancelacion_date_label = QLabel(
            "-"
        )

        details_layout.addRow(
            "Nationality:",
            self.nationality_label
        )

        details_layout.addRow(
            "Passport Number:",
            self.passport_label
        )

        details_layout.addRow(
            "Arrival Date:",
            self.arrival_date_label
        )

        details_layout.addRow(
            "Visa Expiration:",
            self.visa_expiration_label
        )

        details_layout.addRow(
            "Prórroga Expiration:",
            self.prorroga_expiration_label
        )

        details_layout.addRow(
            "Carnet Issue Date:",
            self.carnet_issue_date_label
        )

        details_layout.addRow(
            "Cancelación Date:",
            self.cancelacion_date_label
        )

        details_layout.addRow(
            "Folder Path:",
            self.folder_label
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

            # ==================================
            # Stage Header
            # ==================================

            self.missing_documents_list.addItem(
                f"--- "
                f"{workflow.stage_name} "
                f"---"
            )

            # ==================================
            # Missing Docs
            # ==================================

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

        # ==========================================
        # Process Overview
        # ==========================================

        self.name_label.setText(
            f"Name: {missionary.full_name}"
        )

        self.stage_label.setText(
            f"Current Stage: "
            f"{missionary.current_stage or ''}"
        )

        # ==========================================
        # Details
        # ==========================================

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

        # ==========================================
        # Workflows
        # ==========================================

        self.workflow_list.clear()

        workflows = (
            self.workflow_service
            .get_workflows(
                missionary.id
            )
        )

        logger.debug(
            f"Loaded {len(workflows)} workflows "
            f"for missionary "
            f"{missionary.full_name}"
        )

        for workflow in workflows:
            item_text = (
                f"{workflow.stage_name} - "
                f"{workflow.status}"
            )

            item = QListWidgetItem(
                item_text
            )

            item.setData(
                Qt.UserRole,
                workflow.id
            )

            self.workflow_list.addItem(
                item
            )

        self.load_documents()
        self.load_missing_documents()

    def change_workflow_status(
        self,
        item
    ):
        workflow_id = item.data(
            Qt.UserRole
        )

        logger.info(
            f"Opening workflow status change "
            f"dialog for workflow ID "
            f"{workflow_id}"
        )

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
            logger.debug(
                "Workflow status change cancelled"
            )

            return

        self.workflow_service.update_workflow_status(
            workflow_id,
            selected_status,
        )

        logger.info(
            f"Workflow ID {workflow_id} "
            f"updated to status "
            f"{selected_status}"
        )

        if hasattr(
            self,
            "current_missionary"
        ):
            self.load_missionary(
                self.current_missionary
            )

    def upload_document(self):
        if not hasattr(
            self,
            "current_missionary"
        ):
            logger.warning(
                "Attempted document upload "
                "without loaded missionary"
            )

            return

        logger.info(
            f"Starting document upload for "
            f"{self.current_missionary.full_name}"
        )

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document",
        )

        if not file_path:
            logger.debug(
                "Document upload cancelled "
                "during file selection"
            )

            return

        document_type, ok = (
            QInputDialog.getItem(
                self,
                "Document Type",
                "Select document type:",
                DOCUMENT_TYPES,
                0,
                False,
            )
        )

        if not ok:
            logger.debug(
                "Document upload cancelled "
                "during document type selection"
            )

            return

        workflow_stage, ok = (
            QInputDialog.getItem(
                self,
                "Workflow Stage",
                "Select workflow stage:",
                [
                    "INTERPOL",
                    "CARNET DE EXTRANJERIA",
                    "PRORROGA",
                    "CANCELACION",
                ],
                0,
                False,
            )
        )

        if not ok:
            logger.debug(
                "Document upload cancelled "
                "during workflow stage selection"
            )

            return

        self.document_service.upload_document(
            missionary=self.current_missionary,
            source_file=file_path,
            document_type=document_type,
            workflow_stage=workflow_stage,
        )

        logger.info(
            f"Uploaded document "
            f"{document_type} "
            f"for missionary "
            f"{self.current_missionary.full_name}"
        )

        self.load_documents()
        self.load_missing_documents()

    def load_documents(self):
        self.documents_list.clear()

        documents = (
            self.document_service
            .get_documents(
                self.current_missionary.id
            )
        )

        logger.debug(
            f"Loaded {len(documents)} documents "
            f"for missionary "
            f"{self.current_missionary.full_name}"
        )

        for document in documents:
            self.documents_list.addItem(
                f"{document.document_type} - "
                f"{document.file_name}"
            )

    def delete_missionary(self):
        if not hasattr(
            self,
            "current_missionary"
        ):
            logger.warning(
                "Attempted missionary delete "
                "without loaded missionary"
            )

            return

        logger.warning(
            f"Delete requested for missionary "
            f"{self.current_missionary.full_name}"
        )

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
            logger.info(
                f"Delete cancelled for missionary "
                f"{self.current_missionary.full_name}"
            )

            return

        self.missionary_service.delete_missionary(
            self.current_missionary.id
        )

        logger.info(
            f"Missionary moved to trash: "
            f"{self.current_missionary.full_name}"
        )

        missionaries_page = (
            self.main_window.stack.widget(1)
        )

        missionaries_page.load_data()

        self.main_window.stack.setCurrentIndex(
            1
        )

    def format_date(
        self,
        date_value
    ):
        if not date_value:
            return "-"

        return date_value.strftime(
            "%B %d, %Y"
        )