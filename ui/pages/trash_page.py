import time

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
from ui.foundation.background_loader import LatestRequestLoader

from utils.logger import logger


class TrashPage(QWidget):
    CACHE_TTL_SECONDS = 30.0

    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("TrashPage")

        self.main_window = main_window

        self.missionary_service = MissionaryService()

        self._trashed_snapshot = None

        self._last_refresh_at = 0.0

        self._refresh_loader = LatestRequestLoader(parent=self)

        self._mutation_loader = LatestRequestLoader(parent=self)

        self._row_action_buttons = {}

        self._mutation_loader.busy_changed.connect(
            self._set_action_buttons_enabled
        )

        self.setup_ui()

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

    def request_refresh(self, force=False):
        now = time.monotonic()
        cache_is_fresh = (
            self._trashed_snapshot is not None
            and now - self._last_refresh_at < self.CACHE_TTL_SECONDS
        )
        if cache_is_fresh and not force:
            return False

        service = self.missionary_service
        self._refresh_loader.request(
            service.get_trashed,
            on_success=self._apply_trashed_snapshot,
            on_error=self._trash_refresh_failed,
        )
        return True

    def load_data(self):
        """Compatibility entry point for callers that need a forced refresh."""
        return self.request_refresh(force=True)

    def _apply_trashed_snapshot(self, missionaries):
        self._trashed_snapshot = list(missionaries or [])
        self._last_refresh_at = time.monotonic()
        self._populate_table(self._trashed_snapshot)
        logger.info(
            "Loaded %s trashed missionaries",
            len(self._trashed_snapshot),
        )

    @staticmethod
    def _trash_refresh_failed(error):
        logger.error(
            "Failed to load trash data",
            exc_info=(type(error), error, error.__traceback__),
        )

    def _populate_table(self, missionaries):
        self.table.setSortingEnabled(False)

        self.table.clearContents()

        self.table.setRowCount(len(missionaries))

        self._row_action_buttons = {}

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

            self._row_action_buttons[m.id] = (restore_btn, delete_btn)

        self.table.setSortingEnabled(True)

        self._set_action_buttons_enabled(not self._mutation_loader.busy)

    def _set_action_buttons_enabled(self, enabled):
        for buttons in self._row_action_buttons.values():
            for button in buttons:
                button.setEnabled(bool(enabled))

    def _restore_missionary(self, missionary_id):
        if self._mutation_loader.busy:
            return

        self._refresh_loader.cancel()
        service = self.missionary_service
        self._mutation_loader.request(
            lambda: service.restore_missionary(missionary_id),
            on_success=lambda _result: self._restore_succeeded(missionary_id),
            on_error=lambda error: self._mutation_failed(
                "Restore failed",
                "Failed to restore missionary.",
                error,
            ),
        )

    def _restore_succeeded(self, missionary_id):
        self._remove_from_snapshot(missionary_id)
        self.request_refresh(force=True)
        self._refresh_missionaries_page()
        show_message(
            self,
            "Restored",
            "Missionary restored successfully.",
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

        if self._mutation_loader.busy:
            return

        self._refresh_loader.cancel()
        service = self.missionary_service
        self._mutation_loader.request(
            lambda: service.hard_delete(missionary_id),
            on_success=lambda _result: self._hard_delete_succeeded(
                missionary_id
            ),
            on_error=lambda error: self._mutation_failed(
                "Hard delete failed",
                "Failed to delete missionary.",
                error,
            ),
        )

    def _hard_delete_succeeded(self, missionary_id):
        self._remove_from_snapshot(missionary_id)
        self.request_refresh(force=True)
        show_message(
            self,
            "Deleted",
            "Missionary permanently deleted.",
        )

    def _remove_from_snapshot(self, missionary_id):
        if self._trashed_snapshot is None:
            return
        self._trashed_snapshot = [
            missionary
            for missionary in self._trashed_snapshot
            if getattr(missionary, "id", None) != missionary_id
        ]
        self._populate_table(self._trashed_snapshot)

    def _refresh_missionaries_page(self):
        page = getattr(self.main_window, "missionaries_page", None)
        if page is None:
            return
        refresher = getattr(page, "request_refresh", None)
        if callable(refresher):
            refresher(force=True)
            return
        load_data = getattr(page, "load_data", None)
        if callable(load_data):
            load_data()

    def _mutation_failed(self, log_message, user_message, error):
        logger.error(
            log_message,
            exc_info=(type(error), error, error.__traceback__),
        )
        show_message(
            self,
            "Error",
            user_message,
            kind="critical",
        )
