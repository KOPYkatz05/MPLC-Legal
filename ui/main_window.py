from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QStackedWidget,
)

from PySide6.QtCore import QTimer

from ui.pages.dashboard_page import DashboardPage

from ui.pages.missionaries_page import MissionariesPage

from ui.pages.missionary_detail_page import (
    MissionaryDetailPage,
)

from ui.pages.calendar_page import CalendarPage

from ui.pages.reports_page import ReportsPage

from ui.pages.trash_page import TrashPage

from utils.logger import logger


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Mission Legal Tracker"
        )

        self.resize(1400, 900)

        self.setup_ui()

        # Show expiration alerts shortly after launch
        QTimer.singleShot(
            800, self._show_startup_alerts
        )

    def setup_ui(self):
        central_widget = QWidget()

        central_widget.setObjectName(
            "CentralWidget"
        )

        self.setCentralWidget(central_widget)

        layout = QHBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        central_widget.setLayout(layout)

        # ==========================================
        # Sidebar
        # ==========================================

        self.sidebar = QListWidget()

        self.sidebar.setObjectName("Sidebar")

        self.sidebar.setFixedWidth(210)

        self.sidebar.addItem("  Dashboard")

        self.sidebar.addItem("  Missionaries")

        self.sidebar.addItem("  Appointments")

        self.sidebar.addItem("  Reports")

        self.sidebar.addItem("  Trash")

        # ==========================================
        # Pages
        # ==========================================

        self.stack = QStackedWidget()

        self.dashboard_page = DashboardPage(self)

        self.missionaries_page = MissionariesPage(
            self
        )

        self.detail_page = MissionaryDetailPage(
            self
        )

        self.calendar_page = CalendarPage(self)

        self.reports_page = ReportsPage(self)

        self.trash_page = TrashPage(self)

        self.stack.addWidget(self.dashboard_page)

        self.stack.addWidget(self.missionaries_page)

        self.stack.addWidget(self.detail_page)

        self.stack.addWidget(self.calendar_page)

        self.stack.addWidget(self.reports_page)

        self.stack.addWidget(self.trash_page)

        # ==========================================
        # Navigation
        # ==========================================

        self.sidebar.currentRowChanged.connect(
            self._on_nav_changed
        )

        self.sidebar.setCurrentRow(0)

        # ==========================================
        # Layout
        # ==========================================

        layout.addWidget(self.sidebar)

        layout.addWidget(self.stack, stretch=1)

    # Sidebar index → stack index mapping.
    # Stack order: 0=Dashboard, 1=Missionaries,
    # 2=Detail (no sidebar entry), 3=Calendar,
    # 4=Reports, 5=Trash
    _SIDEBAR_TO_STACK = {
        0: 0,  # Dashboard
        1: 1,  # Missionaries
        2: 3,  # Appointments / Calendar
        3: 4,  # Reports
        4: 5,  # Trash
    }

    def _on_nav_changed(self, sidebar_index):
        stack_index = self._SIDEBAR_TO_STACK.get(
            sidebar_index, 0
        )
        self.stack.setCurrentIndex(stack_index)

        # Refresh page data on navigation
        if stack_index == 0:
            self.dashboard_page.load_data()

        elif stack_index == 1:
            self.missionaries_page.load_data()

        elif stack_index == 3:
            self.calendar_page.load_data()

        elif stack_index == 4:
            self.reports_page.load_data()

        elif stack_index == 5:
            self.trash_page.load_data()

    def _show_startup_alerts(self):
        try:
            from services.alert_service import (
                AlertService,
            )

            from ui.dialogs.expiration_alert_dialog import (
                ExpirationAlertDialog,
            )

            alert_service = AlertService()

            alerts = alert_service.get_all_alerts(
                within_days=30
            )

            if not alerts:
                logger.info(
                    "No expiration alerts to show."
                )
                return

            logger.info(
                f"Showing {len(alerts)} "
                f"expiration alert(s)"
            )

            dialog = ExpirationAlertDialog(
                alerts, parent=self
            )

            dialog.exec()

        except Exception:
            logger.exception(
                "Failed to show startup alerts"
            )
