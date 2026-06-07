from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QWidget,
)

from PySide6.QtCore import Qt

from ui.foundation import (
    DialogFooter,
    PageHeader,
    create_button,
    create_combo_box,
    setup_dialog_shell,
)
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

        self.surface = setup_dialog_shell(
            self,
            surface_width=500,
            surface_min_height=260,
            use_masked_shell=False,
        )

        self._label_to_key = {}

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.surface.setLayout(layout)

        header = PageHeader(
            "Upload Document",
            "Select the document type. "
            "The workflow stage will be filled in automatically.",
        )
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(14)
        body.setLayout(body_layout)

        info = QLabel(
            "Choose the document category before continuing "
            "to the editor."
        )
        info.setObjectName("MutedText")
        info.setWordWrap(True)
        body_layout.addWidget(info)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

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

        body_layout.addLayout(form)
        layout.addWidget(body, stretch=1)

        # ==========================================
        # Buttons
        # ==========================================

        self.cancel_btn = create_button("Cancel", "secondary")

        self.ok_btn = create_button(
            "Continue to Document Editor",
            "primary",
        )

        self.ok_btn.setDefault(True)

        footer = DialogFooter()
        footer.add_action(self.cancel_btn)
        footer.add_action(self.ok_btn)
        layout.addWidget(footer)

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
