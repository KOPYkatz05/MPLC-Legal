from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QComboBox,
    QLabel,
    QFrame,
    QHeaderView,
    QAbstractItemView,
)

from PySide6.QtCore import Qt

from services.missionary_service import (
    MissionaryService,
)

from ui.dialogs.add_missionary_dialog import (
    AddMissionaryDialog,
)

from utils.constants import WORKFLOW_STAGES

from utils.logger import logger


class MissionariesPage(QWidget):
    def __init__(
        self,
        main_window
    ):
        super().__init__()

        self.setObjectName("MissionariesPage")

        self.main_window = main_window

        self.missionary_service = (
            MissionaryService()
        )

        self._all_missionaries = []

        logger.info("Initialized MissionariesPage")

        self.setup_ui()

        self.add_button.clicked.connect(
            self.open_add_dialog
        )

        self.table.cellDoubleClicked.connect(
            self.open_missionary_detail
        )

        self.search_input.textChanged.connect(
            self._apply_filters
        )

        self.stage_filter.currentIndexChanged.connect(
            self._apply_filters
        )

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        # ==========================================
        # Page header
        # ==========================================

        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            32, 20, 32, 20
        )

        header.setLayout(header_layout)

        title = QLabel("Missionaries")

        title.setObjectName("PageTitle")

        self.add_button = QPushButton(
            "+ Add Missionary"
        )

        self.add_button.setObjectName(
            "PrimaryButton"
        )

        self.add_button.setFixedHeight(34)

        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(self.add_button)

        outer.addWidget(header)

        # Divider
        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # ==========================================
        # Search + filter bar
        # ==========================================

        filter_bar = QFrame()

        filter_bar.setObjectName("FilterBar")

        filter_layout = QHBoxLayout()

        filter_layout.setContentsMargins(
            32, 14, 32, 14
        )

        filter_layout.setSpacing(12)

        filter_bar.setLayout(filter_layout)

        self.search_input = QLineEdit()

        self.search_input.setPlaceholderText(
            "Search by name..."
        )

        self.search_input.setObjectName(
            "SearchInput"
        )

        self.search_input.setFixedHeight(34)

        self.search_input.setMaximumWidth(320)

        self.stage_filter = QComboBox()

        self.stage_filter.setObjectName(
            "FilterCombo"
        )

        self.stage_filter.setFixedHeight(34)

        self.stage_filter.addItem("All Stages", None)

        for stage in WORKFLOW_STAGES:
            self.stage_filter.addItem(stage, stage)

        self.result_label = QLabel("")

        self.result_label.setObjectName(
            "ResultLabel"
        )

        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(self.stage_filter)

        filter_layout.addStretch()

        filter_layout.addWidget(self.result_label)

        outer.addWidget(filter_bar)

        # Filter bar bottom divider
        filter_divider = QFrame()

        filter_divider.setObjectName("HeaderDivider")

        filter_divider.setFixedHeight(1)

        outer.addWidget(filter_divider)

        # ==========================================
        # Table
        # ==========================================

        self.table = QTableWidget()

        self.table.setObjectName("MissionaryTable")

        self.table.setColumnCount(5)

        self.table.setHorizontalHeaderLabels([
            "ID",
            "Full Name",
            "Nationality",
            "Passport Number",
            "Current Stage",
        ])

        # Table behaviour
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

        self.table.setSortingEnabled(True)

        # Column widths
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

        self.table.setRowHeight(0, 44)

        outer.addWidget(self.table, stretch=1)

    # ==========================================
    # DATA
    # ==========================================

    def load_data(self):
        try:
            self._all_missionaries = (
                self.missionary_service
                .get_all_missionaries()
            )

            self._apply_filters()

            logger.info(
                f"Loaded "
                f"{len(self._all_missionaries)} "
                f"missionaries into table"
            )

        except Exception:
            logger.exception(
                "Failed to load missionaries table"
            )

    def _apply_filters(self):
        search_text = (
            self.search_input.text().strip().lower()
        )

        selected_stage = (
            self.stage_filter.currentData()
        )

        filtered = []

        for m in self._all_missionaries:
            name = (m.full_name or "").lower()

            preferred = (
                (m.preferred_name or "").lower()
            )

            if search_text and (
                search_text not in name
                and search_text not in preferred
            ):
                continue

            if (
                selected_stage
                and m.current_stage != selected_stage
            ):
                continue

            filtered.append(m)

        self._populate_table(filtered)

        total = len(self._all_missionaries)

        shown = len(filtered)

        if shown == total:
            self.result_label.setText(
                f"{total} missionaries"
            )

        else:
            self.result_label.setText(
                f"{shown} of {total} missionaries"
            )

    def _populate_table(self, missionaries):
        # Disable sorting while populating to
        # avoid row index issues
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

            self.table.setItem(
                row, 4,
                make_item(m.current_stage or ""),
            )

        self.table.setSortingEnabled(True)

    # ==========================================
    # ACTIONS
    # ==========================================

    def open_add_dialog(self):
        try:
            dialog = AddMissionaryDialog(self)

            if dialog.exec():
                logger.info(
                    "Missionary created successfully"
                )

                self.load_data()

        except Exception:
            logger.exception(
                "Failed to open AddMissionaryDialog"
            )

    def open_missionary_detail(self, row, column):
        try:
            id_item = self.table.item(row, 0)

            if not id_item:
                return

            missionary_id = int(id_item.text())

            selected = next(
                (
                    m for m in self._all_missionaries
                    if m.id == missionary_id
                ),
                None,
            )

            if not selected:
                logger.warning(
                    f"Missionary ID {missionary_id} "
                    f"not found"
                )

                return

            logger.info(
                f"Opening detail page for missionary: "
                f"{selected.full_name}"
            )

            self.main_window.detail_page.load_missionary(
                selected
            )

            self.main_window.stack.setCurrentWidget(
                self.main_window.detail_page
            )

        except Exception:
            logger.exception(
                "Failed to open missionary detail page"
            )
