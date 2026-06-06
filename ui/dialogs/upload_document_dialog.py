from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)

from ui.foundation import create_button, create_combo_box
from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STAGES,
    visible_document_keys_for_missionary,
)


class UploadDocumentDialog(QDialog):
    def __init__(
        self,
        parent=None,
        missionary=None,
    ):
        super().__init__(parent)

        self.missionary = missionary

        self.setWindowTitle(
            "Upload Document"
        )

        self.setModal(True)

        self.resize(460, 180)

        self._label_to_key = {}

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.setLayout(layout)

        info = QLabel(
            "Select the document type. "
            "The workflow stage will be filled in automatically."
        )

        info.setWordWrap(True)

        layout.addWidget(info)

        form = QFormLayout()

        # ==========================================
        # Document Type
        # ==========================================

        self.type_combo = create_combo_box()

        for key in visible_document_keys_for_missionary(self.missionary):
            config = DOCUMENTS[key]
            self._label_to_key[config["label"]] = key
            self.type_combo.addItem(
                config["label"],
                key,
            )

        form.addRow(
            "Document Type:",
            self.type_combo,
        )

        # ==========================================
        # Workflow Stage
        # ==========================================

        self.stage_combo = create_combo_box()

        for stage in WORKFLOW_STAGES:
            self.stage_combo.addItem(
                stage,
                stage,
            )

        form.addRow(
            "Workflow Stage:",
            self.stage_combo,
        )

        layout.addLayout(form)

        # ==========================================
        # Buttons
        # ==========================================

        buttons = QHBoxLayout()

        self.cancel_btn = create_button("Cancel", "secondary")

        self.ok_btn = create_button(
            "Continue to Document Editor",
            "primary",
        )

        self.ok_btn.setDefault(True)

        buttons.addStretch()

        buttons.addWidget(self.cancel_btn)

        buttons.addWidget(self.ok_btn)

        layout.addLayout(buttons)

        # ==========================================
        # Connections
        # ==========================================

        self.cancel_btn.clicked.connect(
            self.reject
        )

        self.ok_btn.clicked.connect(
            self.accept
        )

        self.type_combo.currentIndexChanged.connect(
            self._auto_fill_stage
        )

        self._auto_fill_stage()

    def _auto_fill_stage(self):
        doc_key = self.get_document_type()

        if not doc_key:
            return

        stage = DOCUMENTS[doc_key].get("stage")

        if stage and stage in WORKFLOW_STAGES:
            idx = self.stage_combo.findData(stage)

            if idx >= 0:
                self.stage_combo.setCurrentIndex(idx)

        else:
            self.stage_combo.setCurrentIndex(0)

    def get_document_type(self):
        current_data = self.type_combo.currentData()
        if current_data in DOCUMENTS:
            return current_data

        current_text = self.type_combo.currentText()
        return self._label_to_key.get(current_text)

    def get_workflow_stage(self):
        return self.stage_combo.currentData()
