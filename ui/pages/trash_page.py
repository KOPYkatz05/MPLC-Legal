from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QFrame,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)

from PySide6.QtCore import Qt

from services.missionary_service import MissionaryService

from utils.logger import logger


class TrashPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("TrashPage")

        self.main_window = main_window

        self.missionary_service = MissionaryService()

        self.setup_ui()

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        # Header
        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(32, 20, 32, 20)

        header.setLayout(header_layout)

        title = QLabel("Trash / Archive")

        title.setObjectName("PageTitle")

        header_layout.addWidget(title)

        header_layout.addStretch()

        outer.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # Table
        self.table = QTableWidget()

        self.table.setObjectName("MissionaryTable")

        self.table.setColumnCount(6)

        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Full Name",
                "Nationality",
                "Passport Number",
                "Deleted At",
                "Actions",
            ]
        )

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )

        self.table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )

        self.table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        self.table.setAlternatingRowColors(True)

        self.table.verticalHeader().setVisible(False)

        self.table.setShowGrid(False)

        header_view = self.table.horizontalHeader()

        header_view.setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            1, QHeaderView.Stretch
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

        header_view.setSectionResizeMode(
            5, QHeaderView.ResizeToContents
        )

        self.table.setRowHeight(0, 44)

        outer.addWidget(self.table, stretch=1)

    def load_data(self):
        try:
            trashed = (
                self.missionary_service.get_trashed()
            )

            self._populate_table(trashed)

            logger.info(
                f"Loaded {len(trashed)} "
                f"trashed missionaries"
            )

        except Exception:
            logger.exception(
                "Failed to load trash data"
            )

    def _populate_table(self, missionaries):
        self.table.setSortingEnabled(False)

        self.table.clearContents()

        self.table.setRowCount(len(missionaries))

        for row, m in enumerate(missionaries):
            self.table.setRowHeight(row, 40)

            def make_item(text, align=Qt.AlignVCenter):
                item = QTableWidgetItem(text or "")

                item.setTextAlignment(
                    align | Qt.AlignLeft
                )

                return item

            self.table.setItem(
                row, 0,
                make_item(str(m.id)),
            )

            self.table.setItem(
                row, 1,
                make_item(m.full_name or ""),
            )

            self.table.setItem(
                row, 2,
                make_item(m.nationality or ""),
            )

            self.table.setItem(
                row, 3,
                make_item(m.passport_number or ""),
            )

            deleted_str = (
                m.deleted_at.strftime(
                    "%b %d, %Y %H:%M"
                )
                if m.deleted_at
                else "-"
            )

            self.table.setItem(
                row, 4,
                make_item(deleted_str),
            )

            # Action buttons cell
            actions_widget = QWidget()

            actions_layout = QHBoxLayout()

            actions_layout.setContentsMargins(
                4, 2, 4, 2
            )

            actions_layout.setSpacing(8)

            restore_btn = QPushButton("Restore")

            restore_btn.setFixedHeight(28)

            restore_btn.setStyleSheet(
                "QPushButton {"
                "background-color: #059669;"
                "color: white;"
                "border: none;"
                "border-radius: 4px;"
                "padding: 2px 10px;"
                "font-size: 11px;"
                "}"
                "QPushButton:hover {"
                "background-color: #047857;"
                "}"
            )

            restore_btn.clicked.connect(
                lambda _=None, mid=m.id:
                self._restore_missionary(mid)
            )

            delete_btn = QPushButton("Delete Permanently")

            delete_btn.setFixedHeight(28)

            delete_btn.setStyleSheet(
                "QPushButton {"
                "background-color: #DC2626;"
                "color: white;"
                "border: none;"
                "border-radius: 4px;"
                "padding: 2px 10px;"
                "font-size: 11px;"
                "}"
                "QPushButton:hover {"
                "background-color: #B91C1C;"
                "}"
            )

            delete_btn.clicked.connect(
                lambda _=None, mid=m.id:
                self._hard_delete_missionary(mid)
            )

            actions_layout.addWidget(restore_btn)

            actions_layout.addWidget(delete_btn)

            actions_layout.addStretch()

            actions_widget.setLayout(actions_layout)

            self.table.setCellWidget(row, 5, actions_widget)

        self.table.setSortingEnabled(True)

    def _restore_missionary(self, missionary_id):
        try:
            self.missionary_service.restore_missionary(
                missionary_id
            )

            self.load_data()

            # Also refresh the missionaries page
            if hasattr(self.main_window, "missionaries_page"):
                self.main_window.missionaries_page.load_data()

            QMessageBox.information(
                self,
                "Restored",
                "Missionary restored successfully.",
            )

        except Exception:
            logger.exception("Restore failed")

            QMessageBox.critical(
                self,
                "Error",
                "Failed to restore missionary.",
            )

    def _hard_delete_missionary(self, missionary_id):
        response = QMessageBox.question(
            self,
            "Confirm Permanent Delete",
            "Are you sure you want to permanently "
            "delete this missionary?\n\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if response != QMessageBox.Yes:
            return

        try:
            self.missionary_service.hard_delete(
                missionary_id
            )

            self.load_data()

            QMessageBox.information(
                self,
                "Deleted",
                "Missionary permanently deleted.",
            )

        except Exception:
            logger.exception("Hard delete failed")

            QMessageBox.critical(
                self,
                "Error",
                "Failed to delete missionary.",
            )
