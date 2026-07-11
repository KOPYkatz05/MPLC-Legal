from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from PySide6.QtCore import Qt

from services.missionary_service import (
    missionary_display_id,
    MissionaryService,
)
from ui.foundation import (
    configure_data_table,
    create_button,
    create_table,
    show_message,
)

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

        outer.addWidget(self._build_top_bar())

        workspace = QFrame()
        workspace.setObjectName("TrashWorkspace")
        workspace.setAttribute(Qt.WA_StyledBackground, True)
        workspace_layout = QVBoxLayout()
        workspace_layout.setContentsMargins(12, 12, 24, 24)
        workspace_layout.setSpacing(0)
        workspace.setLayout(workspace_layout)

        # Table
        self.table = create_table()
        self.table.setObjectName("TrashTable")

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

        configure_data_table(
            self.table,
            {
                0: QHeaderView.ResizeToContents,
                1: QHeaderView.Stretch,
                2: QHeaderView.ResizeToContents,
                3: QHeaderView.ResizeToContents,
                4: QHeaderView.ResizeToContents,
                5: QHeaderView.ResizeToContents,
            },
            selection_mode=QAbstractItemView.SingleSelection,
            sorting=False,
        )

        workspace_layout.addWidget(self.table, stretch=1)
        outer.addWidget(workspace, stretch=1)

    def _build_top_bar(self):
        frame = QFrame()
        frame.setObjectName("TrashTopBar")
        frame.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(2)
        frame.setLayout(layout)

        title = QLabel("Trash")
        title.setObjectName("TrashTitle")
        subtitle = QLabel("Restore archived records or remove them permanently.")
        subtitle.setObjectName("TrashSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return frame

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
                make_item(missionary_display_id(m)),
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

            restore_btn = create_button(
                "Restore",
                "success",
                fixed_height=28,
            )


            restore_btn.clicked.connect(
                lambda _=None, mid=m.id:
                self._restore_missionary(mid)
            )

            delete_btn = create_button(
                "Delete Permanently",
                "danger",
                fixed_height=28,
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

            show_message(
                self,
                "Restored",
                "Missionary restored successfully.",
            )

        except Exception:
            logger.exception("Restore failed")

            show_message(
                self,
                "Error",
                "Failed to restore missionary.",
                kind="critical",
            )

    def _hard_delete_missionary(self, missionary_id):
        response = show_message(
            self,
            "Confirm Permanent Delete",
            "Are you sure you want to permanently "
            "delete this missionary?\n\n"
            "This action cannot be undone.",
            kind="question",
            buttons="yes_no",
        )

        if response not in {1, 16384}:
            return

        try:
            self.missionary_service.hard_delete(
                missionary_id
            )

            self.load_data()

            show_message(
                self,
                "Deleted",
                "Missionary permanently deleted.",
            )

        except Exception:
            logger.exception("Hard delete failed")

            show_message(
                self,
                "Error",
                "Failed to delete missionary.",
                kind="critical",
            )
