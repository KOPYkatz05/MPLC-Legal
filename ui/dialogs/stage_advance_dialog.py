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
    create_button,
    create_card,
    setup_dialog_shell,
    show_message,
)
from utils.constants import (
    WORKFLOW_STAGES,
    DOCUMENTS,
    required_documents_for_missionary,
)

from utils.logger import logger
from services.document_service import DocumentService
from services.workflow_service import WorkflowService


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
            WorkflowService().get_earliest_incomplete_stage(self.missionary.id)
            or self.missionary.current_stage
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

        docs = DocumentService().get_documents(self.missionary.id)
        self.uploaded_types = {document.document_type for document in docs}

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

        header = QFrame()
        header.setObjectName("StageAdvanceDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = QLabel("Stage Transition")
        title.setObjectName("StageAdvanceDialogTitle")
        subtitle = QLabel(
            "Review required documents before moving this missionary forward."
        )
        subtitle.setObjectName("StageAdvanceDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # ==========================================
        # Body
        # ==========================================

        body = QWidget()

        body.setObjectName("StageAdvanceDialogBody")
        body.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        body_layout = QVBoxLayout()

        body_layout.setContentsMargins(
            18, 16, 18, 16
        )

        body_layout.setSpacing(16)

        body.setLayout(body_layout)

        # Stage flow row
        flow_frame = create_card(object_name="StageAdvanceFlowCard")
        flow_frame.setObjectName("StageAdvanceFlowCard")

        flow_layout = QHBoxLayout()

        flow_layout.setContentsMargins(
            20, 16, 20, 16
        )

        flow_frame.setLayout(flow_layout)

        from_label = QLabel(self.current_stage)

        from_label.setObjectName("StageFromLabel")

        arrow = QLabel("->")

        arrow.setObjectName("FlowArrow")

        to_stage = (
            self.next_stage or "Complete"
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

            docs_frame = create_card(object_name="StageAdvanceDocsCard")
            docs_frame.setObjectName("StageAdvanceDocsCard")

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
                    "OK" if uploaded else "Missing"
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

            warn_icon = QLabel("!")

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
        footer.setObjectName("StageAdvanceDialogFooter")

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

        try:
            if not WorkflowService().advance_missionary(self.missionary.id):
                raise RuntimeError("Missionary could not be advanced")

            logger.info(
                f"Advanced {self.missionary.full_name} "
                f"from {self.current_stage} "
                f"to {self.next_stage}"
            )

            self.accept()

        except Exception:
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
