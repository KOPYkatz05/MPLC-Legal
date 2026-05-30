from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
)


class OCRReviewDialog(QDialog):
    def __init__(
        self,
        parsed_data,
        parent=None,
    ):
        super().__init__(parent)

        self.parsed_data = (
            parsed_data or {}
        )

        self.setWindowTitle(
            "Review OCR Results"
        )

        self.setModal(True)

        self.resize(
            600,
            400,
        )

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.setLayout(layout)

        form = QFormLayout()

        self.surname_edit = QLineEdit(
            self.parsed_data.get(
                "surname",
                "",
            )
        )

        self.given_names_edit = QLineEdit(
            self.parsed_data.get(
                "given_names",
                "",
            )
        )

        self.passport_number_edit = (
            QLineEdit(
                self.parsed_data.get(
                    "passport_number",
                    "",
                )
            )
        )

        self.nationality_edit = (
            QLineEdit(
                self.parsed_data.get(
                    "nationality",
                    "",
                )
            )
        )

        self.birth_date_edit = (
            QLineEdit(
                self.parsed_data.get(
                    "date_of_birth",
                    "",
                )
            )
        )

        self.expiry_date_edit = (
            QLineEdit(
                self.parsed_data.get(
                    "date_of_expiry",
                    "",
                )
            )
        )

        form.addRow(
            "Surname:",
            self.surname_edit,
        )

        form.addRow(
            "Given Names:",
            self.given_names_edit,
        )

        form.addRow(
            "Passport Number:",
            self.passport_number_edit,
        )

        form.addRow(
            "Nationality:",
            self.nationality_edit,
        )

        form.addRow(
            "Date of Birth:",
            self.birth_date_edit,
        )

        form.addRow(
            "Date of Expiry:",
            self.expiry_date_edit,
        )

        layout.addLayout(
            form
        )

        button_layout = QHBoxLayout()

        self.cancel_button = QPushButton(
            "Cancel"
        )

        self.save_button = QPushButton(
            "Save"
        )

        button_layout.addStretch()

        button_layout.addWidget(
            self.cancel_button
        )

        button_layout.addWidget(
            self.save_button
        )

        layout.addLayout(
            button_layout
        )

        self.cancel_button.clicked.connect(
            self.reject
        )

        self.save_button.clicked.connect(
            self.accept
        )

    def get_data(self):
        return {
            "surname": (
                self.surname_edit.text()
            ),
            "given_names": (
                self.given_names_edit.text()
            ),
            "passport_number": (
                self.passport_number_edit.text()
            ),
            "nationality": (
                self.nationality_edit.text()
            ),
            "date_of_birth": (
                self.birth_date_edit.text()
            ),
            "date_of_expiry": (
                self.expiry_date_edit.text()
            ),
        }