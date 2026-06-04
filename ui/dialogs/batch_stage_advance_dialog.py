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

from ui.foundation import create_button, create_table, show_message
from database.db import SessionLocal

from database.models.missionary import Missionary

from database.models.workflow import WorkflowStage

from database.models.stage_history import StageHistory

from utils.constants import (
    WORKFLOW_STAGES,
    WORKFLOW_REQUIREMENTS,
    DOCUMENTS,
)

from utils.logger import logger
from services.onedrive_service import OneDriveService


class BatchStageAdvanceDialog(QDialog):
    def __init__(self, missionary_ids, parent=None):
        super().__init__(parent)

        self.missionary_ids = missionary_ids

        self.setWindowTitle("Batch Stage Advance")

        self.setMinimumWidth(640)

        self.setMinimumHeight(500)

        self._load_data()

        self.setup_ui()

    def _load_data(self):
        session = SessionLocal()

        try:
            self.missionaries = []

            for mid in self.missionary_ids:
                m = (
                    session.query(Missionary)
                    .filter_by(id=mid)
                    .first()
                )

                if m:
                    self.missionaries.append(m)

            self.stage_statuses = []

            for m in self.missionaries:
                stage = m.current_stage

                idx = WORKFLOW_STAGES.index(stage)

                next_stage = (
                    WORKFLOW_STAGES[idx + 1]
                    if idx + 1 < len(WORKFLOW_STAGES)
                    else None
                )

                required = WORKFLOW_REQUIREMENTS.get(
                    stage, []
                )

                docs = (
                    session.query(
                        WorkflowStage
                    )
                    .filter_by(
                        missionary_id=m.id
                    )
                    .all()
                )

                # Check uploaded documents
                from database.models.document import (
                    Document,
                )

                uploaded = {
                    d.document_type
                    for d in (
                        session.query(Document)
                        .filter_by(
                            missionary_id=m.id
                        )
                        .all()
                    )
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

        finally:
            session.close()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.setLayout(layout)

        # Header
        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(24, 18, 24, 18)

        header.setLayout(header_layout)

        title = QLabel("Batch Stage Advance")

        title.setObjectName("PageTitle")

        header_layout.addWidget(title)

        layout.addWidget(header)

        divider = QFrame()

        divider.setFixedHeight(1)

        divider.setObjectName("HeaderDivider")

        layout.addWidget(divider)

        # Body
        body = QWidget()

        body.setObjectName("DialogBody")

        body_layout = QVBoxLayout()

        body_layout.setContentsMargins(24, 20, 24, 20)

        body_layout.setSpacing(16)

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
        table.setObjectName("MissionaryTable")

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

        footer.setObjectName("PageHeader")

        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(24, 12, 24, 12)

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

        session = SessionLocal()

        try:
            onedrive_service = OneDriveService()

            for status in self.stage_statuses:
                stored_missionary = status["missionary"]

                m = (
                    session.query(Missionary)
                    .filter_by(id=stored_missionary.id)
                    .first()
                )

                if not m:
                    continue

                stage = status["stage"]

                next_stage = status["next_stage"]

                workflows = (
                    session.query(WorkflowStage)
                    .filter_by(
                        missionary_id=m.id
                    )
                    .all()
                )

                wf_map = {
                    w.stage_name: w
                    for w in workflows
                }

                curr_wf = wf_map.get(stage)

                if curr_wf:
                    curr_wf.status = "COMPLETED"

                if next_stage:
                    m.current_stage = next_stage

                    next_wf = wf_map.get(next_stage)

                    if next_wf:
                        next_wf.status = "IN PROGRESS"

                    # Record history
                    history = StageHistory(
                        missionary_id=m.id,
                        from_stage=stage,
                        to_stage=next_stage,
                    )

                    session.add(history)

                else:
                    m.status = "ARCHIVED"
                    if m.folder_path:
                        new_folder = (
                            onedrive_service
                            .archive_missionary_folder(
                                m.folder_path
                            )
                        )
                        m.folder_path = str(new_folder)

                logger.info(
                    f"Batch advanced {m.full_name} "
                    f"from {stage} to {next_stage}"
                )

            session.commit()

            self.accept()

        except Exception:
            session.rollback()

            logger.exception(
                "Batch advance failed"
            )

            show_message(
                self,
                "Error",
                "Failed to advance stages.",
                kind="critical",
            )

        finally:
            session.close()
