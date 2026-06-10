from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from services.settings_service import SettingsService
from ui.foundation import AppShell, FLUENT_AVAILABLE, fluent_icon
from ui.pages.calendar_page import CalendarPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.missionaries_page import MissionariesPage
from ui.pages.missionary_detail_page import MissionaryDetailPage
from ui.pages.office_work_page import OfficeWorkPage
from ui.pages.reports_page import ReportsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.trash_page import TrashPage
from utils.i18n import tr
from utils.logger import logger

try:
    from qfluentwidgets import FluentWindow, NavigationItemPosition
except Exception:
    FluentWindow = QMainWindow
    NavigationItemPosition = None


class LoadingSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(52, 52)

    def sizeHint(self):
        return QSize(52, 52)

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _advance(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
        base_pen = QPen(QColor(226, 232, 240), 5)
        base_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 0, 360 * 16)

        accent_pen = QPen(QColor(37, 99, 235), 5)
        accent_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(accent_pen)
        painter.drawArc(rect, -self._angle * 16, -110 * 16)
        painter.end()


class _SidebarCompat:
    def __init__(self, window):
        self.window = window
        self._index_to_key = {
            0: "dashboard",
            1: "missionaries",
            3: "office_work",
            4: "appointments",
            5: "reports",
            6: "trash",
            7: "settings",
        }

    def setCurrentRow(self, row):
        key = self._index_to_key.get(row)
        if key:
            self.window.set_current_key(key)


class _FluentShellCompat:
    def __init__(self, window):
        self.window = window
        self.stack = window.stack

    def set_current_key(self, key):
        self.window.set_current_key(key)

    def set_nav_title(self, key, title):
        self.window.set_nav_title(key, title)


class MainWindow(FluentWindow if FLUENT_AVAILABLE else QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings_service = SettingsService()
        self._nav_widgets = {}
        self._nav_titles = {}
        self._content_overlay = None
        self._content_overlay_blur = None
        self._content_overlay_scrim = None
        self._content_overlay_panel = None
        self._content_overlay_spinner = None
        self._content_overlay_title = None
        self._content_overlay_subtitle = None

        self.setWindowTitle(tr("app_title"))
        self.resize(1400, 900)

        self.setup_ui()

        self.settings_service.language_changed().connect(
            self.retranslate_ui
        )

        QTimer.singleShot(800, self._show_startup_alerts)

    def setup_ui(self):
        self.dashboard_page = DashboardPage(self)
        self.missionaries_page = MissionariesPage(self)
        self.detail_page = MissionaryDetailPage(self)
        self.office_work_page = OfficeWorkPage(self)
        self.calendar_page = CalendarPage(self)
        self.reports_page = ReportsPage(self)
        self.trash_page = TrashPage(self)
        self.settings_page = SettingsPage(self)

        self._nav_keys = {
            "dashboard": "sidebar_dashboard",
            "missionaries": "sidebar_missionaries",
            "office_work": "sidebar_office_work",
            "appointments": "sidebar_appointments",
            "reports": "sidebar_reports",
            "trash": "sidebar_trash",
            "settings": "sidebar_settings",
        }

        if FLUENT_AVAILABLE and hasattr(self, "addSubInterface"):
            self._setup_fluent_shell()
            self.shell = _FluentShellCompat(self)
        else:
            self._setup_fallback_shell()

        self.sidebar = _SidebarCompat(self)
        self.stack.installEventFilter(self)
        self.set_current_key("dashboard")

    def eventFilter(self, watched, event):
        if (
            watched is getattr(self, "stack", None)
            and event.type() == QEvent.Resize
        ):
            self._sync_content_loading_overlay_geometry()
        return super().eventFilter(watched, event)

    def _setup_fluent_shell(self):
        pages = [
            (self.dashboard_page, "dashboard", "HOME", 0),
            (self.missionaries_page, "missionaries", "PEOPLE", 1),
        ]

        for widget, key, icon_name, _stack_index in pages:
            self._add_fluent_nav_page(widget, key, icon_name)

        self.detail_page.setObjectName("MissionaryDetailPage")
        self.stackedWidget.addWidget(self.detail_page)

        for widget, key, icon_name, _stack_index in [
            (self.office_work_page, "office_work", "EDIT", 3),
            (self.calendar_page, "appointments", "CALENDAR", 4),
            (self.reports_page, "reports", "DOCUMENT", 5),
            (self.trash_page, "trash", "DELETE", 6),
            (self.settings_page, "settings", "SETTING", 7),
        ]:
            self._add_fluent_nav_page(widget, key, icon_name)

        self.stack = self.stackedWidget
        self.navigationInterface.setExpandWidth(238)

    def _add_fluent_nav_page(self, widget, key, icon_name):
        widget.setObjectName(widget.objectName() or key)
        title = tr(self._nav_keys[key])
        icon = fluent_icon(icon_name)
        item = self.addSubInterface(
            widget,
            icon,
            title,
            position=NavigationItemPosition.TOP,
        )
        self._nav_widgets[key] = widget
        self._nav_titles[key] = item

    def _setup_fallback_shell(self):
        self.shell = AppShell(tr("app_title"), self)
        self.setCentralWidget(self.shell)
        self.stack = self.shell.stack

        for widget in [
            self.dashboard_page,
            self.missionaries_page,
            self.detail_page,
            self.office_work_page,
            self.calendar_page,
            self.reports_page,
            self.trash_page,
            self.settings_page,
        ]:
            self.stack.addWidget(widget)

        for key, index, group in [
            ("dashboard", 0, "Work"),
            ("missionaries", 1, "Work"),
            ("office_work", 3, "Work"),
            ("appointments", 4, "Work"),
            ("reports", 5, "Insights"),
            ("trash", 6, "System"),
            ("settings", 7, "System"),
        ]:
            self.shell.add_nav_item(key, tr(self._nav_keys[key]), index, group)

        self.shell.navigation_changed.connect(self._on_nav_changed)

    def set_current_key(self, key):
        if not (FLUENT_AVAILABLE and hasattr(self, "switchTo")):
            self.shell.set_current_key(key)
            return

        widget = self._nav_widgets.get(key)
        if widget is None:
            return
        self.switchTo(widget)
        self.navigationInterface.setCurrentItem(widget.objectName())
        self._on_nav_changed(key, self.stack.indexOf(widget))

    def set_nav_title(self, key, title):
        if not (FLUENT_AVAILABLE and hasattr(self, "navigationInterface")):
            self.shell.set_nav_title(key, title)
            return

        widget = self._nav_widgets.get(key)
        if widget is None:
            return
        nav_widget = self.navigationInterface.widget(widget.objectName())
        if nav_widget and hasattr(nav_widget, "setText"):
            nav_widget.setText(title)

    def _on_nav_changed(self, nav_key, stack_index):
        _ = nav_key

        if stack_index == 0:
            self.dashboard_page.load_data()
        elif stack_index == 1:
            self.missionaries_page.load_data()
        elif stack_index == 3:
            self.office_work_page.load_data()
        elif stack_index == 4:
            self.calendar_page.load_data()
        elif stack_index == 5:
            self.reports_page.load_data()
        elif stack_index == 6:
            self.trash_page.load_data()

    def retranslate_ui(self):
        self.setWindowTitle(tr("app_title"))
        for nav_key, translation_key in self._nav_keys.items():
            self.set_nav_title(nav_key, tr(translation_key))
        if hasattr(self.settings_page, "retranslate_ui"):
            self.settings_page.retranslate_ui()
        if hasattr(self.detail_page, "retranslate_ui"):
            self.detail_page.retranslate_ui()

    def go_to_calendar(self):
        self.set_current_key("appointments")

    def show_content_loading_overlay(self, message="Reading document..."):
        self._ensure_content_loading_overlay()
        if self._content_overlay is None:
            return

        self._refresh_content_loading_overlay_snapshot()
        self._content_overlay_title.setText(message or "Reading document...")
        self._content_overlay_subtitle.setText(
            "Please wait while OCR finishes."
        )
        self._sync_content_loading_overlay_geometry()
        self._content_overlay.show()
        self._content_overlay.raise_()
        self._content_overlay_spinner.start()

    def hide_content_loading_overlay(self):
        if self._content_overlay is None:
            return
        self._content_overlay_spinner.stop()
        self._content_overlay.hide()

    def _ensure_content_loading_overlay(self):
        if self._content_overlay is not None:
            return
        if not hasattr(self, "stack") or self.stack is None:
            return

        overlay = QFrame(self.stack)
        overlay.setObjectName("ContentLoadingOverlay")
        overlay.setAttribute(Qt.WA_StyledBackground, True)
        overlay.hide()

        blur = QLabel(overlay)
        blur.setObjectName("ContentLoadingOverlayBlur")
        blur.setScaledContents(True)

        scrim = QWidget(overlay)
        scrim.setObjectName("ContentLoadingOverlayScrim")
        scrim.setAttribute(Qt.WA_StyledBackground, True)

        panel = QFrame(overlay)
        panel.setObjectName("ContentLoadingOverlayPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setFixedWidth(340)
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(28, 26, 28, 26)
        panel_layout.setSpacing(10)
        panel.setLayout(panel_layout)

        spinner = LoadingSpinner(panel)
        title = QLabel("Reading document...")
        title.setObjectName("ContentLoadingOverlayTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Please wait while OCR finishes.")
        subtitle.setObjectName("ContentLoadingOverlaySubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)

        panel_layout.addWidget(spinner, alignment=Qt.AlignCenter)
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch()
        layout.addWidget(panel, alignment=Qt.AlignCenter)
        layout.addStretch()
        overlay.setLayout(layout)

        self._content_overlay = overlay
        self._content_overlay_blur = blur
        self._content_overlay_scrim = scrim
        self._content_overlay_panel = panel
        self._content_overlay_spinner = spinner
        self._content_overlay_title = title
        self._content_overlay_subtitle = subtitle
        self._sync_content_loading_overlay_geometry()

    def _sync_content_loading_overlay_geometry(self):
        if self._content_overlay is None:
            return

        rect = self.stack.rect()
        self._content_overlay.setGeometry(rect)
        self._content_overlay_blur.setGeometry(self._content_overlay.rect())
        self._content_overlay_scrim.setGeometry(self._content_overlay.rect())
        self._content_overlay_blur.lower()
        self._content_overlay_scrim.raise_()
        self._content_overlay_panel.raise_()

    def _refresh_content_loading_overlay_snapshot(self):
        if self._content_overlay is None:
            return

        was_visible = self._content_overlay.isVisible()
        if was_visible:
            self._content_overlay.hide()

        capture = self.stack.grab()
        if not capture.isNull():
            self._content_overlay_blur.setPixmap(self._blur_pixmap(capture))

        if was_visible:
            self._content_overlay.show()

    @staticmethod
    def _blur_pixmap(pixmap, radius=18):
        if pixmap.isNull():
            return pixmap

        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(pixmap)
        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(radius)
        item.setGraphicsEffect(effect)
        scene.addItem(item)

        result = QImage(
            pixmap.size(),
            QImage.Format_ARGB32_Premultiplied,
        )
        result.fill(Qt.transparent)

        painter = QPainter(result)
        scene.render(
            painter,
            QRectF(result.rect()),
            QRectF(0, 0, pixmap.width(), pixmap.height()),
        )
        painter.end()
        return QPixmap.fromImage(result)

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
