from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QWidget,
    QMessageBox,
)

from PySide6.QtCore import Qt

from database.db import SessionLocal

from database.models.document import Document

from database.models.workflow import WorkflowStage

from database.models.missionary import Missionary

from utils.constants import (
    WORKFLOW_STAGES,
    WORKFLOW_REQUIREMENTS,
    DOCUMENTS,
)

from utils.logger import logger


class StageAdvanceDialog(QDialog):

    def __init__(
        self,
        missionary,
        parent=None,
    ):
        super().__init__(parent)

        self.missionary = missionary

        self.setWindowTitle("Advance Stage")

        self.setMinimumWidth(540)

        self.setMinimumHeight(400)

        self._load_data()

        self.setup_ui()

    def _load_data(self):
        self.current_stage = (
            self.missionary.current_stage
            or WORKFLOW_STAGES[0]
        )

        if self.current_stage in WORKFLOW_STAGES:
            idx = WORKFLOW_STAGES.index(
                self.current_stage
            )

            self.next_stage = (
                WORKFLOW_STAGES[idx + 1]
                if idx + 1 < len(WORKFLOW_STAGES)
                else None
            )

        else:
            self.next_stage = WORKFLOW_STAGES[0]

        session = SessionLocal()

        try:
            docs = (
                session.query(Document)
                .filter_by(
                    missionary_id=self.missionary.id
                )
                .all()
            )

            self.uploaded_types = {
                d.document_type for d in docs
            }

        finally:
            session.close()

        required = WORKFLOW_REQUIREMENTS.get(
            self.current_stage, []
        )

        self.doc_statuses = []

        for doc_key in required:
            label = (
                DOCUMENTS.get(doc_key, {})
                .get("label", doc_key)
            )

            uploaded = (
                doc_key in self.uploaded_types
            )

            self.doc_statuses.append(
                (label, uploaded)
            )

        self.all_uploaded = all(
            ok for _, ok in self.doc_statuses
        )

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.setLayout(layout)

        # ==========================================
        # Header
        # ==========================================

        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            24, 18, 24, 18
        )

        header.setLayout(header_layout)

        title = QLabel("Stage Transition")

        title.setObjectName("PageTitle")

        header_layout.addWidget(title)

        layout.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        layout.addWidget(divider)

        # ==========================================
        # Body
        # ==========================================

        body = QWidget()

        body.setStyleSheet(
            "background-color: #F4F4F5;"
        )

        body_layout = QVBoxLayout()

        body_layout.setContentsMargins(
            24, 20, 24, 20
        )

        body_layout.setSpacing(16)

        body.setLayout(body_layout)

        # Stage flow row
        flow_frame = QFrame()

        flow_frame.setStyleSheet(
            "background-color: #FFFFFF; "
            "border: 1px solid #E4E4E7; "
            "border-radius: 10px;"
        )

        flow_layout = QHBoxLayout()

        flow_layout.setContentsMargins(
            20, 16, 20, 16
        )

        flow_frame.setLayout(flow_layout)

        from_label = QLabel(self.current_stage)

        from_label.setStyleSheet(
            "font-weight: 700; "
            "font-size: 14px; "
            "color: #3B82F6; "
            "background: transparent;"
        )

        arrow = QLabel("→")

        arrow.setStyleSheet(
            "color: #A1A1AA; "
            "font-size: 18px; "
            "background: transparent;"
        )

        to_stage = (
            self.next_stage or "✓ Complete"
        )

        to_label = QLabel(to_stage)

        to_label.setStyleSheet(
            "font-weight: 700; "
            "font-size: 14px; "
            "color: #059669; "
            "background: transparent;"
        )

        flow_layout.addWidget(from_label)

        flow_layout.addStretch()

        flow_layout.addWidget(arrow)

        flow_layout.addStretch()

        flow_layout.addWidget(to_label)

        body_layout.addWidget(flow_frame)

        # ==========================================
        # Required docs checklist
        # ==========================================

        if self.doc_statuses:
            section_label = QLabel(
                f"Required documents for "
                f"{self.current_stage}"
            )

            section_label.setObjectName(
                "SectionHeader"
            )

            body_layout.addWidget(section_label)

            docs_frame = QFrame()

            docs_frame.setStyleSheet(
                "background-color: #FFFFFF; "
                "border: 1px solid #E4E4E7; "
                "border-radius: 10px;"
            )

            docs_layout = QVBoxLayout()

            docs_layout.setContentsMargins(
                16, 12, 16, 12
            )

            docs_layout.setSpacing(8)

            docs_frame.setLayout(docs_layout)

            for label, uploaded in (
                self.doc_statuses
            ):
                row = QHBoxLayout()

                icon = QLabel(
                    "✓" if uploaded else "✗"
                )

                icon.setStyleSheet(
                    (
                        "color: #059669; "
                        if uploaded
                        else "color: #DC2626; "
                    )
                    + "font-weight: 700; "
                    + "font-size: 14px; "
                    + "background: transparent;"
                )

                icon.setFixedWidth(20)

                doc_label = QLabel(label)

                doc_label.setStyleSheet(
                    (
                        "color: #18181B; "
                        if uploaded
                        else "color: #DC2626; "
                    )
                    + "font-size: 13px; "
                    + "background: transparent;"
                )

                row.addWidget(icon)

                row.addWidget(doc_label)

                row.addStretch()

                docs_layout.addLayout(row)

            body_layout.addWidget(docs_frame)

        # ==========================================
        # Warning if missing docs
        # ==========================================

        if not self.all_uploaded:
            missing_count = sum(
                1
                for _, ok in self.doc_statuses
                if not ok
            )

            warn = QFrame()

            warn.setStyleSheet(
                "background-color: #FEF3C7; "
                "border: 1px solid #FCD34D; "
                "border-radius: 8px;"
            )

            warn_layout = QHBoxLayout()

            warn_layout.setContentsMargins(
                16, 12, 16, 12
            )

            warn.setLayout(warn_layout)

            warn_icon = QLabel("⚠")

            warn_icon.setStyleSheet(
                "color: #D97706; "
                "font-size: 16px; "
                "background: transparent;"
            )

            warn_text = QLabel(
                f"{missing_count} required "
                f"document(s) are missing. "
                f"You can still advance, but "
                f"this may cause issues."
            )

            warn_text.setStyleSheet(
                "color: #92400E; "
                "font-size: 12px; "
                "background: transparent;"
            )

            warn_text.setWordWrap(True)

            warn_layout.addWidget(warn_icon)

            warn_layout.addSpacing(8)

            warn_layout.addWidget(
                warn_text, stretch=1
            )

            body_layout.addWidget(warn)

        body_layout.addStretch()

        layout.addWidget(body, stretch=1)

        # ==========================================
        # Footer buttons
        # ==========================================

        footer_divider = QFrame()

        footer_divider.setObjectName(
            "HeaderDivider"
        )

        footer_divider.setFixedHeight(1)

        layout.addWidget(footer_divider)

        footer = QFrame()

        footer.setObjectName("PageHeader")

        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(
            24, 12, 24, 12
        )

        footer.setLayout(footer_layout)

        cancel_btn = QPushButton("Cancel")

        cancel_btn.clicked.connect(self.reject)

        footer_layout.addStretch()

        footer_layout.addWidget(cancel_btn)

        if self.next_stage is None:
            advance_label = "Mark as Complete"

        elif self.all_uploaded:
            advance_label = (
                f"Advance to {self.next_stage}"
            )

        else:
            advance_label = (
                "Advance Anyway (missing docs)"
            )

        self.advance_btn = QPushButton(
            advance_label
        )

        self.advance_btn.setObjectName(
            "PrimaryButton"
        )

        self.advance_btn.setFixedHeight(34)

        self.advance_btn.clicked.connect(
            self._do_advance
        )

        footer_layout.addWidget(self.advance_btn)

        layout.addWidget(footer)

    def _do_advance(self):
        if not self.all_uploaded:
            confirm = QMessageBox.question(
                self,
                "Missing Documents",
                "Some required documents are "
                "missing. Advance anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if confirm != QMessageBox.Yes:
                return

        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(
                    id=self.missionary.id
                )
                .first()
            )

            workflows = (
                session.query(WorkflowStage)
                .filter_by(
                    missionary_id=self.missionary.id
                )
                .all()
            )

            wf_map = {
                w.stage_name: w for w in workflows
            }

            # Mark current stage COMPLETED
            curr_wf = wf_map.get(
                self.current_stage
            )

            if curr_wf:
                curr_wf.status = "COMPLETED"

            # Advance missionary stage
            if self.next_stage:
                missionary.current_stage = (
                    self.next_stage
                )

                next_wf = wf_map.get(
                    self.next_stage
                )

                if next_wf:
                    next_wf.status = "IN PROGRESS"

            else:
                missionary.status = "ARCHIVED"

            session.commit()

            logger.info(
                f"Advanced {missionary.full_name} "
                f"from {self.current_stage} "
                f"to {self.next_stage}"
            )

            self.accept()

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to advance missionary stage"
            )

            QMessageBox.critical(
                self,
                "Error",
                "Failed to advance stage. "
                "Check logs for details.",
            )

        finally:
            session.close()
