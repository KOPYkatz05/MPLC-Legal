import ctypes
import sys
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
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
from services.workspace_service import WorkspaceService
from services.notification_feed_service import NotificationFeedService
from ui.foundation import AppShell, FLUENT_AVAILABLE, fluent_icon
from ui.pages.alert_workspace_page import AlertWorkspacePage
from ui.pages.calendar_page import CalendarPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.missionaries_page import MissionariesPage
from ui.pages.missionary_detail_page import MissionaryDetailPage
from ui.pages.missionary_workspace_page import MissionaryWorkspacePage
from ui.pages.office_work_page import OfficeWorkPage
from ui.pages.reports_page import ReportsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.trash_page import TrashPage
from ui.pages.workspaces_page import WorkspacesPage
from utils.i18n import tr
from utils.logger import logger
from utils.window_diagnostics import log_top_level_windows

try:
    from qfluentwidgets import FluentWindow, NavigationItemPosition
except Exception:
    FluentWindow = QMainWindow
    NavigationItemPosition = None


WINDOW_RESIZE_BORDER_WIDTH = 8
WM_NCHITTEST = 0x0084
WM_WINDOWPOSCHANGED = 0x0047
WM_EXITSIZEMOVE = 0x0232
HTCAPTION = 2
HTMAXBUTTON = 9
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MAXIMIZEBOX = 0x00010000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


@dataclass
class NavigationContext:
    widget: QWidget
    nav_key: str | None
    state: object = None


class _WindowsPoint(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class _WindowsMessage(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", _WindowsPoint),
    ]


def windows_message_id(message):
    try:
        return _WindowsMessage.from_address(int(message)).message
    except Exception:
        return None


def resize_hit_test(frame_rect, global_pos, border_width=WINDOW_RESIZE_BORDER_WIDTH):
    if frame_rect is None or global_pos is None or not frame_rect.contains(global_pos):
        return None

    left = frame_rect.left() <= global_pos.x() < frame_rect.left() + border_width
    right = frame_rect.right() - border_width < global_pos.x() <= frame_rect.right()
    top = frame_rect.top() <= global_pos.y() < frame_rect.top() + border_width
    bottom = frame_rect.bottom() - border_width < global_pos.y() <= frame_rect.bottom()

    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return None


def title_bar_hit_test(global_pos, drag_rect=None, maximize_rect=None):
    """Return native Windows title-bar zones for the custom app chrome."""
    if global_pos is None:
        return None
    if maximize_rect is not None and maximize_rect.contains(global_pos):
        return HTMAXBUTTON
    if drag_rect is not None and drag_rect.contains(global_pos):
        return HTCAPTION
    return None


def native_snap_window_style(style):
    """Keep custom chrome while advertising normal window capabilities to Windows."""
    return style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU


def enable_native_snap_for_window(window):
    if not sys.platform.startswith("win") or window is None:
        return False
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        current_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        desired_style = native_snap_window_style(current_style)
        if desired_style != current_style:
            user32.SetWindowLongW(hwnd, GWL_STYLE, desired_style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE
                | SWP_NOSIZE
                | SWP_NOZORDER
                | SWP_NOACTIVATE
                | SWP_FRAMECHANGED,
            )
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


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

        accent_pen = QPen(QColor(14, 165, 172), 5)
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
            4: "office_work",
            5: "appointments",
            6: "reports",
            7: "trash",
            8: "workspaces",
            9: "settings",
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


class MainWindow(QMainWindow):
    _windows_toast_available = None

    def __init__(self):
        super().__init__()

        self.settings_service = SettingsService()
        self.workspace_service = WorkspaceService()
        self._nav_widgets = {}
        self._nav_titles = {}
        self._content_overlay = None
        self._content_overlay_blur = None
        self._content_overlay_scrim = None
        self._content_overlay_panel = None
        self._content_overlay_spinner = None
        self._content_overlay_title = None
        self._content_overlay_subtitle = None
        self._content_overlay_subtitle_timer = QTimer(self)
        self._content_overlay_subtitle_timer.setInterval(2500)
        self._content_overlay_subtitle_timer.timeout.connect(
            self._advance_content_loading_subtitle
        )
        self._content_overlay_subtitles = []
        self._content_overlay_subtitle_index = 0
        self._startup_alerts = []
        self._native_layout_refresh_pending = False

        self.setWindowTitle(tr("app_title"))
        if sys.platform.startswith("win"):
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setWindowFlag(Qt.WindowSystemMenuHint, True)
            self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
            self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.resize(1400, 900)

        self.setup_ui()

        self.settings_service.language_changed().connect(
            self.retranslate_ui
        )

        QTimer.singleShot(0, lambda: log_top_level_windows("main-window-created"))
        QTimer.singleShot(800, self._load_startup_alerts)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform.startswith("win"):
            enable_native_snap_for_window(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_native_layout_refresh()

    def _schedule_native_layout_refresh(self):
        if self._native_layout_refresh_pending:
            return
        self._native_layout_refresh_pending = True
        QTimer.singleShot(0, self._refresh_native_window_layout)

    def _refresh_native_window_layout(self):
        self._native_layout_refresh_pending = False
        shell = getattr(self, "shell", None)
        if shell is None:
            return

        for widget in (shell, getattr(shell, "stack", None)):
            layout = widget.layout() if widget is not None else None
            if layout is not None:
                layout.invalidate()
                layout.activate()

        stack = getattr(shell, "stack", None)
        current_page = stack.currentWidget() if stack is not None else None
        if current_page is not None:
            current_page.updateGeometry()
            layout = current_page.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

            column_refresher = getattr(current_page, "_apply_column_widths", None)
            if callable(column_refresher):
                column_refresher()

    def refresh_workspace_actions(self):
        if hasattr(self, "detail_page") and hasattr(
            self.detail_page,
            "refresh_workspace_actions",
        ):
            self.detail_page.refresh_workspace_actions()

    def setup_ui(self):
        self.dashboard_page = DashboardPage(self)
        self.dashboard_page.startup_alerts_requested.connect(
            self._open_startup_alerts
        )
        self.missionaries_page = MissionariesPage(self)
        self.detail_page = MissionaryDetailPage(self)
        self.missionary_workspace_page = MissionaryWorkspacePage(self)
        self.alert_workspace_page = AlertWorkspacePage(self)
        self.office_work_page = OfficeWorkPage(self)
        self.calendar_page = CalendarPage(self)
        self.reports_page = ReportsPage(self)
        self.trash_page = TrashPage(self)
        self.workspaces_page = WorkspacesPage(self)
        self.settings_page = SettingsPage(self)

        self._nav_keys = {
            "dashboard": "sidebar_dashboard",
            "missionaries": "sidebar_missionaries",
            "office_work": "sidebar_office_work",
            "appointments": "sidebar_appointments",
            "reports": "sidebar_reports",
            "trash": "sidebar_trash",
            "workspaces": "sidebar_workspaces",
            "settings": "sidebar_settings",
        }
        self._detail_navigation_stack = []

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

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "shell"):
            title_bar = getattr(self.shell, "title_bar", None)
            if title_bar is not None:
                title_bar.refresh_maximize_state()

    def nativeEvent(self, event_type, message):
        message_id = windows_message_id(message)
        if (
            sys.platform.startswith("win")
            and event_type in {"windows_generic_MSG", "windows_dispatcher_MSG"}
            and message_id in {WM_WINDOWPOSCHANGED, WM_EXITSIZEMOVE}
        ):
            self._schedule_native_layout_refresh()
        if (
            sys.platform.startswith("win")
            and event_type in {"windows_generic_MSG", "windows_dispatcher_MSG"}
            and message_id == WM_NCHITTEST
            and not self.isFullScreen()
        ):
            global_pos = QCursor.pos()
            hit = None
            if not self.isMaximized():
                hit = resize_hit_test(self.frameGeometry(), global_pos)
            if hit is None:
                title_bar = getattr(getattr(self, "shell", None), "title_bar", None)
                if title_bar is not None:
                    hit = title_bar_hit_test(
                        global_pos,
                        title_bar.global_drag_rect(),
                        title_bar.global_maximize_rect(),
                    )
            if hit is not None:
                return True, hit
        return super().nativeEvent(event_type, message)

    def _setup_fluent_shell(self):
        pages = [
            (self.dashboard_page, "dashboard", "HOME", 0),
            (self.missionaries_page, "missionaries", "PEOPLE", 1),
        ]

        for widget, key, icon_name, _stack_index in pages:
            self._add_fluent_nav_page(widget, key, icon_name)

        self.detail_page.setObjectName("MissionaryDetailPage")
        self.stackedWidget.addWidget(self.detail_page)
        self.alert_workspace_page.setObjectName("AlertWorkspacePage")
        self.stackedWidget.addWidget(self.alert_workspace_page)
        self.missionary_workspace_page.setObjectName("MissionaryWorkspacePage")
        self.stackedWidget.addWidget(self.missionary_workspace_page)

        for widget, key, icon_name, _stack_index in [
            (self.office_work_page, "office_work", "EDIT", 3),
            (self.calendar_page, "appointments", "CALENDAR", 4),
            (self.reports_page, "reports", "DOCUMENT", 5),
            (self.trash_page, "trash", "DELETE", 6),
            (self.workspaces_page, "workspaces", "EDIT", 7),
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
            self.alert_workspace_page,
            self.office_work_page,
            self.calendar_page,
            self.reports_page,
            self.trash_page,
            self.workspaces_page,
            self.settings_page,
            self.missionary_workspace_page,
        ]:
            self.stack.addWidget(widget)

        for key, index, group in [
            ("dashboard", 0, "Work"),
            ("missionaries", 1, "Work"),
            ("office_work", 4, "Work"),
            ("appointments", 5, "Work"),
            ("reports", 6, "Insights"),
            ("trash", 7, "System"),
            ("workspaces", 8, "System"),
            ("settings", 9, "System"),
        ]:
            self.shell.add_nav_item(key, tr(self._nav_keys[key]), index, group)

        self.shell.navigation_changed.connect(self._on_nav_changed)

    def set_current_key(self, key):
        current_widget = getattr(self.stack, "currentWidget", lambda: None)()
        if (
            current_widget is getattr(self, "detail_page", None)
        ):
            self._detail_navigation_stack.clear()

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
        if nav_key == "dashboard" or stack_index == 0:
            self.dashboard_page.request_refresh(force=False)
        elif nav_key == "missionaries" or stack_index == 1:
            self.missionaries_page.load_data()
        elif nav_key == "office_work" or stack_index == 4:
            refresher = getattr(self.office_work_page, "request_refresh", None)
            if callable(refresher):
                refresher()
            else:
                self.office_work_page.load_data()
        elif nav_key == "appointments" or stack_index == 5:
            self.calendar_page.load_data()
        elif nav_key == "reports" or stack_index == 6:
            self.reports_page.load_data()
        elif nav_key == "trash" or stack_index == 7:
            self.trash_page.load_data()
        elif nav_key == "workspaces" or stack_index == 8:
            self.workspaces_page.load_data()

    def retranslate_ui(self):
        self.setWindowTitle(tr("app_title"))
        for nav_key, translation_key in self._nav_keys.items():
            self.set_nav_title(nav_key, tr(translation_key))
        if hasattr(self.settings_page, "retranslate_ui"):
            self.settings_page.retranslate_ui()
        if hasattr(self.workspaces_page, "retranslate_ui"):
            self.workspaces_page.retranslate_ui()
        if hasattr(self.missionaries_page, "retranslate_ui"):
            self.missionaries_page.retranslate_ui()
        if hasattr(self.detail_page, "retranslate_ui"):
            self.detail_page.retranslate_ui()
        if hasattr(self.missionary_workspace_page, "retranslate_ui"):
            self.missionary_workspace_page.retranslate_ui()

    def go_to_calendar(self):
        self.set_current_key("appointments")

    def _nav_key_for_widget(self, widget):
        for key, nav_widget in getattr(self, "_nav_widgets", {}).items():
            if nav_widget is widget:
                return key
        return None

    def _capture_current_view_context(self):
        current_widget = getattr(self.stack, "currentWidget", lambda: None)()
        if current_widget is None:
            return None

        nav_key = self._nav_key_for_widget(current_widget)
        snapshot = None
        capture = getattr(current_widget, "capture_navigation_state", None)
        if callable(capture):
            try:
                snapshot = capture()
            except Exception:
                logger.exception(
                    "Failed to capture navigation state for %s",
                    current_widget.objectName() or current_widget.__class__.__name__,
                )
        return NavigationContext(
            widget=current_widget,
            nav_key=nav_key,
            state=snapshot,
        )

    def _set_current_widget_without_reload(self, widget, nav_key=None):
        if widget is None:
            return

        if FLUENT_AVAILABLE and hasattr(self, "switchTo"):
            self.switchTo(widget)
            if (
                nav_key
                and hasattr(self, "navigationInterface")
                and nav_key in self._nav_widgets
            ):
                nav_widget = self._nav_widgets.get(nav_key)
                if nav_widget is not None:
                    self.navigationInterface.setCurrentItem(
                        nav_widget.objectName()
                    )
            return

        self.stack.setCurrentWidget(widget)
        if (
            nav_key
            and hasattr(self, "shell")
            and hasattr(self.shell, "_buttons")
            and nav_key in self.shell._buttons
        ):
            self.shell._buttons[nav_key].setChecked(True)

    def _restore_navigation_context(self, context):
        if context is None:
            self._set_current_widget_without_reload(
                self.missionaries_page,
                "missionaries",
            )
            load_data = getattr(self.missionaries_page, "load_data", None)
            if callable(load_data):
                load_data()
            return

        widget = getattr(context, "widget", None)
        nav_key = getattr(context, "nav_key", None)
        state = getattr(context, "state", None)
        if widget is None:
            self._restore_navigation_context(None)
            return

        self._set_current_widget_without_reload(widget, nav_key)

        restore = getattr(widget, "restore_navigation_state", None)
        if callable(restore):
            try:
                restore(state)
                return
            except Exception:
                logger.exception(
                    "Failed to restore navigation state for %s",
                    widget.objectName() or widget.__class__.__name__,
                )

        load_data = getattr(widget, "load_data", None)
        if callable(load_data):
            try:
                load_data()
            except Exception:
                logger.exception(
                    "Failed to refresh restored page %s",
                    widget.objectName() or widget.__class__.__name__,
                )

    def _clear_detail_navigation_stack_if_detail_visible(self):
        if getattr(self.stack, "currentWidget", lambda: None)() is getattr(
            self,
            "detail_page",
            None,
        ):
            self._detail_navigation_stack.clear()

    def return_from_missionary_detail(self):
        detail_page = getattr(self, "detail_page", None)
        confirm_leave = getattr(detail_page, "confirm_leave_detail", None)
        if callable(confirm_leave) and not confirm_leave():
            return False

        if self._detail_navigation_stack:
            context = self._detail_navigation_stack.pop()
        else:
            context = None

        self._restore_navigation_context(context)
        return True

    def open_missionary_detail(self, missionary_id):
        try:
            from database.db import SessionLocal
            from database.models.missionary import Missionary

            context = self._capture_current_view_context()

            session = SessionLocal()
            try:
                missionary = (
                    session.query(Missionary)
                    .filter_by(id=missionary_id)
                    .first()
                )
                if missionary is None:
                    logger.warning(
                        "Missionary ID %s not found",
                        missionary_id,
                    )
                    return False

                if context is not None:
                    self._detail_navigation_stack.append(context)

                self.detail_page.load_missionary(missionary)
                self.stack.setCurrentWidget(self.detail_page)

                if (
                    FLUENT_AVAILABLE
                    and hasattr(self, "navigationInterface")
                    and "missionaries" in self._nav_widgets
                ):
                    widget = self._nav_widgets["missionaries"]
                    self.navigationInterface.setCurrentItem(
                        widget.objectName()
                    )

                return True
            finally:
                session.close()

        except Exception:
            logger.exception(
                "Failed to open missionary detail for ID %s",
                missionary_id,
            )
            return False

    def open_alert_workspace(self, task_id, return_key="dashboard"):
        try:
            self._clear_detail_navigation_stack_if_detail_visible()
            self.alert_workspace_page.load_task(task_id, return_key=return_key)
            self.stack.setCurrentWidget(self.alert_workspace_page)

            if (
                FLUENT_AVAILABLE
                and hasattr(self, "navigationInterface")
                and return_key in self._nav_widgets
            ):
                widget = self._nav_widgets[return_key]
                self.navigationInterface.setCurrentItem(widget.objectName())

            return True
        except Exception:
            logger.exception(
                "Failed to open alert workspace for task ID %s",
                task_id,
            )
            return False

    def open_missionary_workspace(self, missionary, workspace):
        try:
            self._clear_detail_navigation_stack_if_detail_visible()
            self.missionary_workspace_page.load_workspace(missionary, workspace)
            self.stack.setCurrentWidget(self.missionary_workspace_page)

            if (
                FLUENT_AVAILABLE
                and hasattr(self, "navigationInterface")
                and "missionaries" in self._nav_widgets
            ):
                widget = self._nav_widgets["missionaries"]
                self.navigationInterface.setCurrentItem(widget.objectName())

            return True
        except Exception:
            logger.exception("Failed to open missionary workspace")
            return False

    def show_content_loading_overlay(
        self,
        message="Reading document...",
        subtitles=None,
        subtitle_interval_ms=2500,
    ):
        self._ensure_content_loading_overlay()
        if self._content_overlay is None:
            return

        self._refresh_content_loading_overlay_snapshot()
        self._content_overlay_title.setText(message or "Reading document...")
        self._stop_content_loading_subtitle_rotation()
        if subtitles:
            self._start_content_loading_subtitle_rotation(
                subtitles,
                subtitle_interval_ms,
            )
        else:
            self._content_overlay_subtitle.setText(
                tr("ocr_loading_default_subtitle")
            )
        self._sync_content_loading_overlay_geometry()
        self._content_overlay.show()
        self._content_overlay.raise_()
        self._content_overlay_spinner.start()

    def hide_content_loading_overlay(self):
        if self._content_overlay is None:
            return
        self._stop_content_loading_subtitle_rotation()
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
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(10)
        panel.setLayout(panel_layout)

        spinner = LoadingSpinner(panel)
        title = QLabel("Reading document...")
        title.setObjectName("ContentLoadingOverlayTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel(tr("ocr_loading_default_subtitle"))
        subtitle.setObjectName("ContentLoadingOverlaySubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)

        panel_layout.addWidget(spinner, alignment=Qt.AlignCenter)
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 20)
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

    def _start_content_loading_subtitle_rotation(
        self,
        subtitles,
        interval_ms=2500,
    ):
        clean_subtitles = [subtitle for subtitle in subtitles if subtitle]
        if not clean_subtitles:
            return
        self._content_overlay_subtitles = clean_subtitles
        self._content_overlay_subtitle_index = 0
        self._content_overlay_subtitle.setText(clean_subtitles[0])
        self._content_overlay_subtitle_timer.setInterval(
            max(250, int(interval_ms))
        )
        if len(clean_subtitles) > 1:
            self._content_overlay_subtitle_timer.start()

    def _stop_content_loading_subtitle_rotation(self):
        self._content_overlay_subtitle_timer.stop()
        self._content_overlay_subtitles = []
        self._content_overlay_subtitle_index = 0

    def _advance_content_loading_subtitle(self):
        if not self._content_overlay_subtitles:
            self._content_overlay_subtitle_timer.stop()
            return
        self._content_overlay_subtitle_index = (
            self._content_overlay_subtitle_index + 1
        ) % len(self._content_overlay_subtitles)
        self._content_overlay_subtitle.setText(
            self._content_overlay_subtitles[
                self._content_overlay_subtitle_index
            ]
        )

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

    def _load_startup_alerts(self):
        try:
            feed_service = NotificationFeedService(self.settings_service)
            alerts = feed_service.startup_items()
            self._startup_alerts = list(alerts or [])

            if not alerts:
                logger.info("No startup notification items.")
                self.dashboard_page.set_startup_alerts([])
                return

            logger.info(
                "Loaded %s startup notification item(s)",
                len(self._startup_alerts),
            )
            self.dashboard_page.set_startup_alerts(self._startup_alerts)
            self._show_windows_startup_notification(feed_service)
            log_top_level_windows("startup-alerts-loaded", delay_ms=0)

        except Exception:
            logger.exception("Failed to load startup alerts")

    def _open_startup_alerts(self):
        if not self._startup_alerts:
            return

        try:
            from ui.dialogs.startup_alerts_dialog import StartupAlertsDialog

            logger.info(
                "Opening %s startup notification item(s) on request",
                len(self._startup_alerts),
            )
            dialog = StartupAlertsDialog(self._startup_alerts, self)
            dialog.exec()
        except Exception:
            logger.exception("Failed to open startup alerts")

    def _show_windows_startup_notification(self, feed_service):
        summary = feed_service.windows_summary(self._startup_alerts)
        if not summary:
            return

        today = date.today().isoformat()
        state = self.settings_service.get_windows_notification_state()
        if (
            state.get("date") == today
            and state.get("fingerprint") == summary["fingerprint"]
        ):
            return

        if not self._send_windows_toast(summary["title"], summary["body"]):
            return

        self.settings_service.set_windows_notification_state(
            today,
            summary["fingerprint"],
        )

    @staticmethod
    def _send_windows_toast(title, body):
        if MainWindow._windows_toast_available is False:
            return False
        try:
            from winotify import Notification
        except ImportError:
            MainWindow._windows_toast_available = False
            logger.info("Windows notifications unavailable: winotify is not installed")
            return False

        MainWindow._windows_toast_available = True
        try:
            toast = Notification(
                app_id="Mission Legal",
                title=title,
                msg=body,
            )
            toast.show()
            return True
        except Exception:
            logger.exception("Failed to show Windows notification")
            return False
