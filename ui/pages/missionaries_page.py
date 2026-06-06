from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QFileDialog,
    QDialog,
)

from PySide6.QtCore import Qt

from services.missionary_service import (
    missionary_display_id,
    MissionaryService,
)

from services.export_service import ExportService
from ui.foundation import (
    FilterBar,
    PageHeader,
    configure_data_table,
    create_button,
    create_combo_box,
    create_line_edit,
    create_menu,
    create_table,
    divider,
    show_message,
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

        self.export_service = ExportService()

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

        self.nationality_filter.currentIndexChanged.connect(
            self._apply_filters
        )

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        self.add_button = create_button(
            "+ Add Missionary",
            "primary",
        )

        self.export_button = create_button(
            "Export to Excel",
            "secondary",
        )

        self.export_button.clicked.connect(
            self._export_excel
        )

        header = PageHeader(
            "Missionaries",
            "Track legal workflow status and documents.",
            [self.export_button, self.add_button],
        )

        outer.addWidget(header)

        outer.addWidget(divider())

        # ==========================================
        # Search + filter bar
        # ==========================================

        filter_bar = FilterBar()

        self.search_input = create_line_edit(
            "Search by ID or name..."
        )

        self.search_input.setMaximumWidth(280)

        self.stage_filter = create_combo_box()

        self.stage_filter.addItem("All Stages", None)

        for stage in WORKFLOW_STAGES:
            self.stage_filter.addItem(stage, stage)

        self.nationality_filter = create_combo_box()

        self.nationality_filter.setMaximumWidth(180)

        self.nationality_filter.addItem(
            "All Nationalities", None
        )

        self.batch_button = create_button(
            "Batch Actions",
            "secondary",
        )

        self.batch_button.clicked.connect(
            self._batch_actions
        )

        self.result_label = QLabel("")

        self.result_label.setObjectName(
            "ResultLabel"
        )

        filter_bar.add_filter(self.search_input)
        filter_bar.add_filter(self.stage_filter)
        filter_bar.add_filter(
            self.nationality_filter
        )
        filter_bar.add_spacer()
        filter_bar.add_filter(self.batch_button)
        filter_bar.add_filter(self.result_label)

        outer.addWidget(filter_bar)

        outer.addWidget(divider())

        # ==========================================
        # Table
        # ==========================================

        self.table = create_table()

        self.table.setColumnCount(5)

        self.table.setHorizontalHeaderLabels([
            "Missionary ID",
            "Full Name",
            "Nationality",
            "Passport Number",
            "Current Stage",
        ])

        configure_data_table(
            self.table,
            {
                0: QHeaderView.ResizeToContents,
                1: QHeaderView.Stretch,
                2: QHeaderView.ResizeToContents,
                3: QHeaderView.ResizeToContents,
                4: QHeaderView.ResizeToContents,
            },
            selection_mode=QAbstractItemView.MultiSelection,
            sorting=True,
        )

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

            # Update nationality filter dropdown
            existing = [
                self.nationality_filter.itemText(i)
                for i in range(
                    self.nationality_filter.count()
                )
            ]

            for m in self._all_missionaries:
                nat = (m.nationality or "").strip()

                if nat and nat not in existing:
                    self.nationality_filter.addItem(
                        nat, nat
                    )

                    existing.append(nat)

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

        selected_nationality = (
            self.nationality_filter.currentData()
        )

        filtered = []

        for m in self._all_missionaries:
            display_id = (
                missionary_display_id(m).lower()
            )

            name = (m.full_name or "").lower()

            preferred = (
                (m.preferred_name or "").lower()
            )

            if search_text and (
                search_text not in display_id
                and search_text not in name
                and search_text not in preferred
            ):
                continue

            if (
                selected_stage
                and m.current_stage != selected_stage
            ):
                continue

            if (
                selected_nationality
                and (m.nationality or "")
                != selected_nationality
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
                make_item(missionary_display_id(m)),
            )

            self.table.item(row, 0).setData(
                Qt.UserRole,
                m.id,
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
            dialog = AddMissionaryDialog(
                self.main_window
            )

            if dialog.exec():
                logger.info(
                    "Missionary created successfully"
                )

                self.load_data()

        except Exception:
            logger.exception(
                "Failed to open AddMissionaryDialog"
            )

    def _export_excel(self):
        if not self._all_missionaries:
            show_message(
                self,
                "No Data",
                "No missionaries to export.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Missionaries to Excel",
            "missionaries_export.xlsx",
            "Excel Files (*.xlsx)",
        )

        if not file_path:
            return

        ok = self.export_service.export_missionaries_to_excel(
            self._all_missionaries,
            file_path,
        )

        if ok:
            show_message(
                self,
                "Export Complete",
                f"Exported "
                f"{len(self._all_missionaries)} "
                f"missionaries to:\n{file_path}",
            )

        else:
            show_message(
                self,
                "Export Failed",
                "Failed to export. "
                "Check logs for details.",
                kind="critical",
            )

    def open_missionary_detail(self, row, column):
        # Only open detail if single row selected
        if len(self.table.selectedItems()) > 5:
            return

        try:
            id_item = self.table.item(row, 0)

            if not id_item:
                return

            missionary_id = id_item.data(
                Qt.UserRole
            )

            if missionary_id is None:
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

    def _batch_actions(self):
        selected_rows = set()

        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            show_message(
                self,
                "No Selection",
                "Select at least one missionary "
                "from the table.",
            )

            return

        ids = []

        for row in selected_rows:
            id_item = self.table.item(row, 0)

            if id_item:
                missionary_id = id_item.data(
                    Qt.UserRole
                )

                if missionary_id is None:
                    missionary_id = int(
                        id_item.text()
                    )

                ids.append(missionary_id)

        # Show simple menu
        menu = create_menu("", self)

        advance_action = menu.addAction(
            "Advance Stage"
        )

        action = menu.exec(
            self.batch_button.mapToGlobal(
                self.batch_button.rect().bottomLeft()
            )
        )

        if action == advance_action:
            from ui.dialogs.batch_stage_advance_dialog import (
                BatchStageAdvanceDialog,
            )

            dialog = BatchStageAdvanceDialog(
                ids, parent=self
            )

            if dialog.exec() == QDialog.Accepted:
                self.load_data()

                # Also refresh dashboard
                if hasattr(
                    self.main_window, "dashboard_page"
                ):
                    self.main_window.dashboard_page.load_data()
