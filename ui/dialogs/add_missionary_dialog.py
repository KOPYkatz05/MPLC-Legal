from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QDateEdit,
)

from PySide6.QtCore import QDate

from services.missionary_service import (
    MissionaryService,
)
from ui.foundation import DialogFooter, create_button

from utils.logger import logger


class AddMissionaryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.missionary_service = (
            MissionaryService()
        )

        self.setWindowTitle(
            "Add Missionary"
        )

        self.setMinimumWidth(400)

        logger.info(
            "Opened Add Missionary dialog"
        )

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.setLayout(layout)

        # ======================================
        # Full Name
        # ======================================

        layout.addWidget(
            QLabel("Full Name")
        )

        self.full_name_input = (
            QLineEdit()
        )

        layout.addWidget(
            self.full_name_input
        )

        # ======================================
        # Preferred Name
        # ======================================

        layout.addWidget(
            QLabel("Preferred Name")
        )

        self.preferred_name_input = (
            QLineEdit()
        )

        layout.addWidget(
            self.preferred_name_input
        )

        # ======================================
        # Nationality
        # ======================================

        layout.addWidget(
            QLabel("Nationality")
        )

        self.nationality_input = (
            QLineEdit()
        )

        layout.addWidget(
            self.nationality_input
        )

        # ======================================
        # Passport Number
        # ======================================

        layout.addWidget(
            QLabel("Passport Number")
        )

        self.passport_input = (
            QLineEdit()
        )

        layout.addWidget(
            self.passport_input
        )

        # ======================================
        # Arrival Date
        # ======================================

        layout.addWidget(
            QLabel("Arrival Date")
        )

        self.arrival_date_input = (
            QDateEdit()
        )

        self.arrival_date_input.setCalendarPopup(
            True
        )

        self.arrival_date_input.setDate(
            QDate.currentDate()
        )

        layout.addWidget(
            self.arrival_date_input
        )

        # ======================================
        # Visa Expiration
        # ======================================

        layout.addWidget(
            QLabel("Visa Expiration")
        )

        self.visa_expiration_input = (
            QDateEdit()
        )

        self.visa_expiration_input.setCalendarPopup(
            True
        )

        self.visa_expiration_input.setDate(
            QDate.currentDate()
        )

        layout.addWidget(
            self.visa_expiration_input
        )

        # ======================================
        # Save Button
        # ======================================

        footer = DialogFooter()

        self.save_button = create_button(
            "Save Missionary",
            "primary",
        )

        self.save_button.clicked.connect(
            self.save_missionary
        )

        footer.add_action(
            self.save_button
        )

        layout.addWidget(footer)

    def save_missionary(self):
        try:
            full_name = (
                self.full_name_input.text()
                .strip()
            )

            if not full_name:
                logger.warning(
                    "Attempted to create "
                    "missionary without "
                    "full name"
                )

                QMessageBox.warning(
                    self,
                    "Error",
                    "Full name is required.",
                )

                return

            missionary = (
                self.missionary_service
                .create_missionary(
                    full_name=full_name,

                    preferred_name=(
                        self.preferred_name_input
                        .text()
                        .strip()
                    ),

                    nationality=(
                        self.nationality_input
                        .text()
                        .strip()
                    ),

                    passport_number=(
                        self.passport_input
                        .text()
                        .strip()
                    ),

                    arrival_date=(
                        self.arrival_date_input
                        .date()
                        .toPython()
                    ),

                    visa_expiration=(
                        self.visa_expiration_input
                        .date()
                        .toPython()
                    ),
                )
            )

            logger.info(
                f"Successfully created "
                f"missionary from dialog: "
                f"{missionary.full_name}"
            )

            self.accept()

        except Exception:
            logger.exception(
                "Failed to save missionary "
                "from AddMissionaryDialog"
            )

            QMessageBox.critical(
                self,
                "Error",
                (
                    "An unexpected error "
                    "occurred while saving "
                    "the missionary."
                ),
            )
