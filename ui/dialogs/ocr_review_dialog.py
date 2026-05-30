from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QLabel,
)


OCR_FIELD_LABELS = {
    "passport_number": "Passport Number",
    "full_name": "Full Name",
    "date_of_birth": "Date of Birth",
    "nationality": "Nationality",
    "passport_expiration": "Passport Expiration",
    "arrival_date": "Arrival Date",
    "interpol_appointment_date": "Interpol Appointment Date",
    "biometric_appointment_date": "Biometric Appointment Date",
    "pickup_appointment_date": "Pickup Appointment Date",
    "carnet_number": "Carnet Number",
    "carnet_issue_date": "Carnet Issue Date",
    "residency_expiration": "Residency Expiration",
    "prorroga_expiration": "Prórroga Expiration",
    "cancelacion_date": "Cancelación Date",
}


class OCRReviewDialog(QDialog):
    def __init__(
        self,
        ocr_fields,
        parsed_data,
        parent=None,
    ):
        super().__init__(parent)

        self.ocr_fields = ocr_fields

        self.parsed_data = parsed_data or {}

        self.field_edits = {}

        self.setWindowTitle(
            "Review Extracted Data"
        )

        self.setModal(True)

        dialog_height = (
            160 + len(ocr_fields) * 52
        )

        self.resize(520, dialog_height)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.setLayout(layout)

        # ==========================================
        # Instructions
        # ==========================================

        info = QLabel(
            "OCR has extracted the following data from your document. "
            "Please review and correct any errors before saving."
        )

        info.setWordWrap(True)

        layout.addWidget(info)

        # ==========================================
        # Fields
        # ==========================================

        form = QFormLayout()

        for field in self.ocr_fields:
            label = OCR_FIELD_LABELS.get(
                field,
                field.replace("_", " ").title(),
            )

            raw_value = self.parsed_data.get(field, "")

            if raw_value and not isinstance(
                raw_value,
                str,
            ):
                raw_value = str(raw_value)

            edit = QLineEdit(raw_value or "")

            self.field_edits[field] = edit

            form.addRow(
                f"{label}:",
                edit,
            )

        layout.addLayout(form)

        # ==========================================
        # Buttons
        # ==========================================

        button_layout = QHBoxLayout()

        self.skip_btn = QPushButton(
            "Skip (no OCR data)"
        )

        self.save_btn = QPushButton(
            "Save Extracted Data"
        )

        self.save_btn.setDefault(True)

        button_layout.addStretch()

        button_layout.addWidget(self.skip_btn)

        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)

        # ==========================================
        # Connections
        # ==========================================

        self.skip_btn.clicked.connect(
            self.reject
        )

        self.save_btn.clicked.connect(
            self.accept
        )

    def get_data(self):
        return {
            field: edit.text().strip()
            for field, edit
            in self.field_edits.items()
        }
