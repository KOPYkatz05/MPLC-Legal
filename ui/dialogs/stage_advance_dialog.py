from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QWidget,
)

from PySide6.QtCore import Qt

from ui.foundation import (
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    PageHeader,
    create_button,
    create_card,
    setup_dialog_shell,
    show_message,
)
from database.db import SessionLocal

from database.models.document import Document

from database.models.workflow import WorkflowStage

from database.models.missionary import Missionary

from database.models.stage_history import StageHistory

from utils.constants import (
    WORKFLOW_STAGES,
    DOCUMENTS,
    required_documents_for_missionary,
)

from utils.logger import logger
from services.onedrive_service import OneDriveService
from services.expiration_rules import apply_stage_completion_expiration


class StageAdvanceDialog(MaskDialogBase):

    def __init__(
        self,
        missionary,
        parent=None,
    ):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = FLUENT_AVAILABLE and fluent_parent is not None
        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.missionary = missionary

        self.setWindowTitle("Advance Stage")
        self.surface = setup_dialog_shell(
            self,
            surface_width=540,
            surface_min_height=400,
        )

        self._load_data()

        self.setup_ui()

    def _onDone(self, code):
        if self._use_fluent_dialog:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

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

        required = required_documents_for_missionary(
            self.current_stage,
            self.missionary,
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

        self.surface.setLayout(layout)

        # ==========================================
        # Header
        # ==========================================

        header = PageHeader(
            "Stage Transition",
            "Review required documents before moving this missionary forward.",
        )

        layout.addWidget(header)

        # ==========================================
        # Body
        # ==========================================

        body = QWidget()

        body.setObjectName("DialogBody")
        body.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        body_layout = QVBoxLayout()

        body_layout.setContentsMargins(
            24, 20, 24, 20
        )

        body_layout.setSpacing(16)

        body.setLayout(body_layout)

        # Stage flow row
        flow_frame = create_card()

        flow_layout = QHBoxLayout()

        flow_layout.setContentsMargins(
            20, 16, 20, 16
        )

        flow_frame.setLayout(flow_layout)

        from_label = QLabel(self.current_stage)

        from_label.setObjectName("StageFromLabel")

        arrow = QLabel("→")

        arrow.setObjectName("FlowArrow")

        to_stage = (
            self.next_stage or "✓ Complete"
        )

        to_label = QLabel(to_stage)

        to_label.setObjectName("StageToLabel")

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

            docs_frame = create_card()

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

                icon.setObjectName(
                    "StatusSuccess" if uploaded else "StatusDanger"
                )

                icon.setFixedWidth(20)

                doc_label = QLabel(label)

                doc_label.setObjectName(
                    "BodyText" if uploaded else "DangerText"
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

            warn.setObjectName("WarningBanner")

            warn_layout = QHBoxLayout()

            warn_layout.setContentsMargins(
                16, 12, 16, 12
            )

            warn.setLayout(warn_layout)

            warn_icon = QLabel("⚠")

            warn_icon.setObjectName("WarningIcon")

            warn_text = QLabel(
                f"{missing_count} required "
                f"document(s) are missing. "
                f"You can still advance, but "
                f"this may cause issues."
            )

            warn_text.setObjectName("WarningBannerText")

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

        footer = DialogFooter()

        cancel_btn = create_button("Cancel", "secondary")

        cancel_btn.clicked.connect(self.reject)

        footer.add_action(cancel_btn)

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

        self.advance_btn = create_button(advance_label, "primary")

        self.advance_btn.clicked.connect(
            self._do_advance
        )

        footer.add_action(self.advance_btn)

        layout.addWidget(footer)

    def _do_advance(self):
        if not self.all_uploaded:
            confirm = show_message(
                self,
                "Missing Documents",
                "Some required documents are "
                "missing. Advance anyway?",
                kind="question",
                buttons="yes_no",
            )

            if confirm not in {1, 16384}:
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

            apply_stage_completion_expiration(
                missionary,
                self.current_stage,
            )

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

                # Record history
                history = StageHistory(
                    missionary_id=missionary.id,
                    from_stage=self.current_stage,
                    to_stage=self.next_stage,
                )

                session.add(history)

            else:
                missionary.status = "ARCHIVED"
                if missionary.folder_path:
                    new_folder = (
                        OneDriveService()
                        .archive_missionary_folder(
                            missionary.folder_path
                        )
                    )
                    missionary.folder_path = str(new_folder)

                history = StageHistory(
                    missionary_id=missionary.id,
                    from_stage=self.current_stage,
                    to_stage="ARCHIVED",
                )

                session.add(history)

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

            show_message(
                self,
                "Error",
                "Failed to advance stage. "
                "Check logs for details.",
                kind="critical",
            )

        finally:
            session.close()
