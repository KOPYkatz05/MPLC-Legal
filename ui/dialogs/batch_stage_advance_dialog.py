from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from PySide6.QtCore import Qt

from ui.foundation import (
    create_button,
    create_table,
    setup_dialog_shell,
    show_message,
)
from utils.constants import (
    WORKFLOW_STAGES,
    required_documents_for_missionary,
)

from utils.logger import logger
from services.document_service import DocumentService
from services.missionary_service import MissionaryService
from services.workflow_service import WorkflowService


class BatchStageAdvanceDialog(QDialog):
    def __init__(self, missionary_ids, parent=None):
        super().__init__(parent)

        self.missionary_ids = missionary_ids

        self.setWindowTitle("Batch Stage Advance")
        self.surface = setup_dialog_shell(
            self,
            surface_width=640,
            surface_min_height=500,
            use_masked_shell=False,
        )

        self._load_data()

        self.setup_ui()

    def _load_data(self):
        missionary_service = MissionaryService()
        document_service = DocumentService()
        self.missionaries = []

        for missionary_id in self.missionary_ids:
            missionary = missionary_service.get_missionary(missionary_id)
            if missionary:
                self.missionaries.append(missionary)

        self.stage_statuses = []

        for m in self.missionaries:
                stage = m.current_stage

                idx = WORKFLOW_STAGES.index(stage)

                next_stage = (
                    WORKFLOW_STAGES[idx + 1]
                    if idx + 1 < len(WORKFLOW_STAGES)
                    else None
                )

                required = required_documents_for_missionary(
                    stage,
                    m,
                )

                uploaded = {
                    d.document_type
                    for d in document_service.get_documents(m.id)
                }

                all_uploaded = all(
                    req in uploaded
                    for req in required
                )

                self.stage_statuses.append({
                    "missionary": m,
                    "stage": stage,
                    "next_stage": next_stage,
                    "all_uploaded": all_uploaded,
                    "required": len(required),
                    "missing": len(required)
                    - len(
                        [
                            r
                            for r in required
                            if r in uploaded
                        ]
                    ),
                })


    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.surface.setLayout(layout)

        # Header
        header = QFrame()

        header.setObjectName("BatchStageDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)

        header_layout = QVBoxLayout()

        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)

        header.setLayout(header_layout)

        title = QLabel("Batch Stage Advance")

        title.setObjectName("BatchStageDialogTitle")

        header_layout.addWidget(title)

        subtitle = QLabel("Review document readiness before moving selected missionaries.")
        subtitle.setObjectName("BatchStageDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Body
        body = QWidget()

        body.setObjectName("BatchStageDialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()

        body_layout.setContentsMargins(18, 16, 18, 16)

        body_layout.setSpacing(12)

        body.setLayout(body_layout)

        # Summary
        count = len(self.missionaries)

        summary = QLabel(
            f"Advancing {count} "
            f"missionary(s) to the next stage."
        )

        summary.setObjectName("BodyText")

        body_layout.addWidget(summary)

        # Table
        table = create_table()
        table.setObjectName("BatchStageTable")

        table.setColumnCount(5)

        table.setHorizontalHeaderLabels(
            [
                "Name",
                "Current",
                "Next",
                "Docs",
                "Status",
            ]
        )

        table.setRowCount(len(self.stage_statuses))

        table.setAlternatingRowColors(True)

        table.verticalHeader().setVisible(False)

        table.setShowGrid(False)

        table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        header_view = table.horizontalHeader()

        header_view.setSectionResizeMode(
            0, QHeaderView.Stretch
        )

        header_view.setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )

        for row, status in enumerate(
            self.stage_statuses
        ):
            table.setRowHeight(row, 36)

            m = status["missionary"]

            table.setItem(
                row, 0,
                QTableWidgetItem(m.full_name),
            )
            table.setItem(
                row, 1,
                QTableWidgetItem(
                    status["stage"]
                ),
            )

            table.setItem(
                row, 2,
                QTableWidgetItem(
                    status["next_stage"] or "Complete"
                ),
            )

            table.setItem(
                row, 3,
                QTableWidgetItem(
                    f"{status['required'] - status['missing']}"
                    f" / {status['required']}"
                ),
            )

            status_text = (
                "Ready"
                if status["all_uploaded"]
                else "Missing docs"
            )

            status_item = QTableWidgetItem(status_text)

            status_item.setForeground(
                (
                    Qt.GlobalColor.darkGreen
                    if status["all_uploaded"]
                    else Qt.GlobalColor.darkRed
                )
            )

            table.setItem(row, 4, status_item)

        body_layout.addWidget(table)

        body_layout.addStretch()

        layout.addWidget(body, stretch=1)

        # Footer
        footer = QFrame()

        footer.setObjectName("BatchStageDialogFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)

        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(18, 12, 18, 12)
        footer_layout.setSpacing(8)

        footer.setLayout(footer_layout)

        cancel_btn = create_button("Cancel", "secondary")

        cancel_btn.clicked.connect(self.reject)

        footer_layout.addStretch()

        footer_layout.addWidget(cancel_btn)

        any_missing = any(
            not s["all_uploaded"]
            for s in self.stage_statuses
        )

        if any_missing:
            label = (
                "Advance Anyway (some missing)"
            )

        else:
            label = "Advance All"

        advance_btn = create_button(label, "primary")

        advance_btn.clicked.connect(
            self._do_batch_advance
        )

        footer_layout.addWidget(advance_btn)

        layout.addWidget(footer)

    def _do_batch_advance(self):
        any_missing = any(
            not s["all_uploaded"]
            for s in self.stage_statuses
        )

        if any_missing:
            confirm = show_message(
                self,
                "Confirm",
                "Some missionaries have missing "
                "documents. Advance anyway?",
                kind="question",
                buttons="yes_no",
            )

            if confirm not in {1, 16384}:
                return

        try:
            WorkflowService().advance_missionaries(
                [status["missionary"].id for status in self.stage_statuses]
            )
            for status in self.stage_statuses:
                logger.info(
                    f"Batch advanced {status['missionary'].full_name} "
                    f"from {status['stage']} to {status['next_stage']}"
                )

            self.accept()

        except Exception:
            logger.exception(
                "Batch advance failed"
            )

            show_message(
                self,
                "Error",
                "Failed to advance stages.",
                kind="critical",
            )
