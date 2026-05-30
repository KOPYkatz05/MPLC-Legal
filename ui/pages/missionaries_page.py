from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from services.missionary_service import (
    MissionaryService,
)

from ui.dialogs.add_missionary_dialog import (
    AddMissionaryDialog,
)

from utils.logger import logger


class MissionariesPage(QWidget):
    def __init__(
        self,
        main_window
    ):
        super().__init__()

        self.main_window = main_window

        self.missionary_service = (
            MissionaryService()
        )

        logger.info(
            "Initialized MissionariesPage"
        )

        self.setup_ui()

        self.add_button.clicked.connect(
            self.open_add_dialog
        )

        self.table.cellDoubleClicked.connect(
            self.open_missionary_detail
        )

        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.setLayout(layout)

        # ======================================
        # Add Missionary Button
        # ======================================

        self.add_button = QPushButton(
            "Add Missionary"
        )

        layout.addWidget(
            self.add_button
        )

        # ======================================
        # Missionaries Table
        # ======================================

        self.table = QTableWidget()

        self.table.setColumnCount(5)

        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Full Name",
                "Preferred Name",
                "Nationality",
                "Passport Number",
            ]
        )

        layout.addWidget(
            self.table
        )

    def load_data(self):
        try:
            missionaries = (
                self.missionary_service
                .get_all_missionaries()
            )

            self.table.clearContents()

            self.table.setRowCount(
                len(missionaries)
            )

            for row, missionary in enumerate(
                missionaries
            ):
                self.table.setItem(
                    row,
                    0,
                    QTableWidgetItem(
                        str(missionary.id)
                    ),
                )

                self.table.setItem(
                    row,
                    1,
                    QTableWidgetItem(
                        missionary.full_name or ""
                    ),
                )

                self.table.setItem(
                    row,
                    2,
                    QTableWidgetItem(
                        missionary.preferred_name or ""
                    ),
                )

                self.table.setItem(
                    row,
                    3,
                    QTableWidgetItem(
                        missionary.nationality or ""
                    ),
                )

                self.table.setItem(
                    row,
                    4,
                    QTableWidgetItem(
                        missionary.passport_number or ""
                    ),
                )

            logger.info(
                f"Loaded "
                f"{len(missionaries)} "
                f"missionaries into table"
            )

        except Exception:
            logger.exception(
                "Failed to load "
                "missionaries table"
            )

    def open_add_dialog(self):
        try:
            logger.info(
                "Opening Add "
                "Missionary dialog"
            )

            dialog = AddMissionaryDialog(
                self
            )

            if dialog.exec():
                logger.info(
                    "Missionary created "
                    "successfully from dialog"
                )

                self.load_data()

            else:
                logger.info(
                    "Add Missionary "
                    "dialog cancelled"
                )

        except Exception:
            logger.exception(
                "Failed to open "
                "AddMissionaryDialog"
            )

    def open_missionary_detail(
        self,
        row,
        column
    ):
        try:
            missionary_id_item = (
                self.table.item(row, 0)
            )

            if not missionary_id_item:
                logger.warning(
                    "No missionary ID "
                    "found in selected row"
                )

                return

            missionary_id = int(
                missionary_id_item.text()
            )

            missionaries = (
                self.missionary_service
                .get_all_missionaries()
            )

            selected_missionary = None

            for missionary in missionaries:
                if missionary.id == missionary_id:
                    selected_missionary = missionary
                    break

            if not selected_missionary:
                logger.warning(
                    f"Missionary ID "
                    f"{missionary_id} "
                    f"not found"
                )

                return

            logger.info(
                f"Opening detail page "
                f"for missionary: "
                f"{selected_missionary.full_name}"
            )

            self.main_window.detail_page.load_missionary(
                selected_missionary
            )

            self.main_window.stack.setCurrentWidget(
                self.main_window.detail_page
            )

        except Exception:
            logger.exception(
                "Failed to open "
                "missionary detail page"
            )