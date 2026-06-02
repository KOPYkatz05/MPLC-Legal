from PySide6.QtWidgets import (
    QMainWindow,
)

from PySide6.QtCore import QTimer

from ui.foundation import AppShell
from ui.pages.dashboard_page import DashboardPage
from ui.pages.missionaries_page import MissionariesPage
from ui.pages.missionary_detail_page import MissionaryDetailPage
from ui.pages.calendar_page import CalendarPage
from ui.pages.reports_page import ReportsPage
from ui.pages.trash_page import TrashPage
from ui.pages.settings_page import SettingsPage
from services.settings_service import SettingsService
from utils.i18n import tr
from utils.logger import logger


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings_service = SettingsService()

        self.setWindowTitle(tr("app_title"))
        self.resize(1400, 900)

        self.setup_ui()

        self.settings_service.language_changed().connect(
            self.retranslate_ui
        )

        QTimer.singleShot(800, self._show_startup_alerts)

    def setup_ui(self):
        self.shell = AppShell(tr("app_title"), self)
        self.setCentralWidget(self.shell)
        self.stack = self.shell.stack

        self.dashboard_page = DashboardPage(self)
        self.missionaries_page = MissionariesPage(self)
        self.detail_page = MissionaryDetailPage(self)
        self.calendar_page = CalendarPage(self)
        self.reports_page = ReportsPage(self)
        self.trash_page = TrashPage(self)
        self.settings_page = SettingsPage(self)

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.missionaries_page)
        self.stack.addWidget(self.detail_page)
        self.stack.addWidget(self.calendar_page)
        self.stack.addWidget(self.reports_page)
        self.stack.addWidget(self.trash_page)
        self.stack.addWidget(self.settings_page)

        self._nav_keys = {
            "dashboard": "sidebar_dashboard",
            "missionaries": "sidebar_missionaries",
            "appointments": "sidebar_appointments",
            "reports": "sidebar_reports",
            "trash": "sidebar_trash",
            "settings": "sidebar_settings",
        }

        self.shell.add_nav_item(
            "dashboard", tr("sidebar_dashboard"), 0, "Work"
        )
        self.shell.add_nav_item(
            "missionaries", tr("sidebar_missionaries"), 1, "Work"
        )
        self.shell.add_nav_item(
            "appointments", tr("sidebar_appointments"), 3, "Work"
        )
        self.shell.add_nav_item(
            "reports", tr("sidebar_reports"), 4, "Insights"
        )
        self.shell.add_nav_item(
            "trash", tr("sidebar_trash"), 5, "System"
        )
        self.shell.add_nav_item(
            "settings", tr("sidebar_settings"), 6, "System"
        )

        self.shell.navigation_changed.connect(self._on_nav_changed)
        self.shell.set_current_key("dashboard")

    def _on_nav_changed(self, nav_key, stack_index):
        _ = nav_key

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

    def retranslate_ui(self):
        self.setWindowTitle(tr("app_title"))
        for nav_key, translation_key in self._nav_keys.items():
            self.shell.set_nav_title(nav_key, tr(translation_key))
        if hasattr(self.settings_page, "retranslate_ui"):
            self.settings_page.retranslate_ui()
        if hasattr(self.detail_page, "retranslate_ui"):
            self.detail_page.retranslate_ui()

    def go_to_calendar(self):
        self.shell.set_current_key("appointments")

    def _show_startup_alerts(self):
        try:
            from services.alert_service import AlertService
            from ui.dialogs.expiration_alert_dialog import (
                ExpirationAlertDialog,
            )

            alert_service = AlertService()
            alerts = alert_service.get_all_alerts(within_days=30)

            if not alerts:
                logger.info("No expiration alerts to show.")
                return

            logger.info(f"Showing {len(alerts)} expiration alert(s)")
            dialog = ExpirationAlertDialog(alerts, parent=self)
            dialog.exec()

        except Exception:
            logger.exception("Failed to show startup alerts")
