from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QMainWindow, QSizePolicy, QWidget

from ui.foundation import AppShell, AppTitleBar
from ui.main_window import (
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTCAPTION,
    HTLEFT,
    HTMAXBUTTON,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    WS_MAXIMIZEBOX,
    WS_MINIMIZEBOX,
    WS_SYSMENU,
    WS_THICKFRAME,
    native_snap_window_style,
    resize_hit_test,
    title_bar_hit_test,
)


class RecordingWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.calls = []

    def showMinimized(self):
        self.calls.append("minimize")

    def showMaximized(self):
        self.calls.append("maximize")

    def showNormal(self):
        self.calls.append("restore")

    def close(self):
        self.calls.append("close")
        return True

    def isMaximized(self):
        return self.calls[-1:] == ["maximize"]


class FakeMouseEvent:
    def __init__(self, button=Qt.LeftButton, buttons=Qt.LeftButton, global_pos=None):
        self._button = button
        self._buttons = buttons
        self._global_pos = global_pos or QPoint(20, 20)
        self.accepted = False

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def globalPosition(self):
        return SimpleNamespace(toPoint=lambda: self._global_pos)

    def accept(self):
        self.accepted = True


def test_app_shell_creates_custom_title_bar(qapp):
    _ = qapp
    shell = AppShell("Mission Legal Tracker")

    assert isinstance(shell.title_bar, AppTitleBar)
    assert shell.title_bar.objectName() == "AppTitleBar"
    assert shell.title_bar.drag_region.objectName() == "AppTitleDragRegion"
    assert shell.title_bar.minimize_button.objectName() == "AppWindowControlButton"
    assert shell.title_bar.close_button.objectName() == "AppWindowCloseButton"


def test_app_shell_hidden_pages_do_not_force_a_large_window_minimum(qapp):
    _ = qapp
    shell = AppShell("Mission Legal Tracker")
    large_page = QWidget()
    large_page.setMinimumWidth(1400)
    shell.stack.addWidget(large_page)

    assert shell.stack.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert shell.stack.minimumWidth() == 0
    assert shell.minimumSizeHint().width() < 400


def test_app_shell_menu_button_toggles_labeled_navigation(qapp, qtbot):
    _ = qapp
    shell = AppShell("Mission Legal Tracker")
    shell.add_nav_item("dashboard", "Dashboard", 0, "Work")
    shell.add_nav_item("office_work", "Tasks", 1, "Work")

    assert shell.sidebar.width() == shell.COLLAPSED_SIDEBAR_WIDTH
    icon_x = shell._buttons["dashboard"].icon_label.geometry().x()
    assert shell.menu_button.text_label.isHidden()
    assert shell._buttons["dashboard"].text_label.isHidden()

    shell.menu_button.click()
    assert shell._sidebar_animation is not None
    qtbot.waitUntil(
        lambda: shell.COLLAPSED_SIDEBAR_WIDTH
        < shell.sidebar.width()
        < shell.EXPANDED_SIDEBAR_WIDTH
    )
    assert shell._buttons["dashboard"].icon_label.geometry().x() == icon_x
    qtbot.waitUntil(lambda: shell._sidebar_animation is None)

    assert shell.sidebar.width() == shell.EXPANDED_SIDEBAR_WIDTH
    assert shell.menu_button.navigation_text() == "Menu"
    assert shell._buttons["dashboard"].navigation_text() == "Dashboard"
    assert shell._buttons["office_work"].navigation_text() == "Tasks"
    assert shell._buttons["dashboard"].icon_label.geometry().x() == icon_x
    assert not shell.menu_button.text_label.isHidden()
    assert not shell._buttons["dashboard"].text_label.isHidden()

    shell.menu_button.click()
    qtbot.waitUntil(lambda: shell._sidebar_animation is None)

    assert shell.sidebar.width() == shell.COLLAPSED_SIDEBAR_WIDTH
    assert shell._buttons["dashboard"].icon_label.geometry().x() == icon_x
    assert shell._buttons["dashboard"].toolButtonStyle() == Qt.ToolButtonIconOnly
    assert shell.menu_button.text_label.isHidden()
    assert shell._buttons["dashboard"].text_label.isHidden()


def test_app_title_bar_window_buttons_call_parent_window(qapp):
    _ = qapp
    window = RecordingWindow()
    shell = AppShell("Mission Legal Tracker", window)
    window.setCentralWidget(shell)

    shell.title_bar.minimize_button.click()
    shell.title_bar.maximize_button.click()
    shell.title_bar.maximize_button.click()
    shell.title_bar.close_button.click()

    assert window.calls == ["minimize", "maximize", "restore", "close"]


def test_app_title_bar_double_click_toggles_maximize(qapp):
    _ = qapp
    window = RecordingWindow()
    shell = AppShell("Mission Legal Tracker", window)
    window.setCentralWidget(shell)

    event = FakeMouseEvent()
    shell.title_bar.drag_region.mouseDoubleClickEvent(event)

    assert event.accepted is True
    assert window.calls == ["maximize"]


def test_app_title_bar_drag_uses_system_move(monkeypatch, qapp):
    _ = qapp
    calls = []

    class FakeHandle:
        def startSystemMove(self):
            calls.append("system_move")
            return True

    fake_window = SimpleNamespace(
        frameGeometry=lambda: QRect(0, 0, 100, 100),
        windowHandle=lambda: FakeHandle(),
    )
    title_bar = AppTitleBar("Mission Legal Tracker")
    monkeypatch.setattr(title_bar.drag_region, "window", lambda: fake_window)

    event = FakeMouseEvent()
    title_bar.drag_region.mousePressEvent(event)

    assert event.accepted is True
    assert calls == ["system_move"]


def test_main_window_resize_hit_test_returns_normal_windows_edges():
    rect = QRect(100, 100, 500, 400)

    assert resize_hit_test(rect, QPoint(100, 100)) == HTTOPLEFT
    assert resize_hit_test(rect, QPoint(599, 100)) == HTTOPRIGHT
    assert resize_hit_test(rect, QPoint(100, 499)) == HTBOTTOMLEFT
    assert resize_hit_test(rect, QPoint(599, 499)) == HTBOTTOMRIGHT
    assert resize_hit_test(rect, QPoint(100, 250)) == HTLEFT
    assert resize_hit_test(rect, QPoint(599, 250)) == HTRIGHT
    assert resize_hit_test(rect, QPoint(250, 100)) == HTTOP
    assert resize_hit_test(rect, QPoint(250, 499)) == HTBOTTOM


def test_main_window_resize_hit_test_ignores_content_area():
    rect = QRect(100, 100, 500, 400)

    assert resize_hit_test(rect, QPoint(250, 250)) is None
    assert resize_hit_test(rect, QPoint(80, 250)) is None


def test_title_bar_hit_test_exposes_native_caption_and_snap_layout_button():
    drag_rect = QRect(100, 100, 500, 34)
    maximize_rect = QRect(500, 102, 34, 30)

    assert title_bar_hit_test(QPoint(250, 115), drag_rect, maximize_rect) == HTCAPTION
    assert title_bar_hit_test(QPoint(510, 115), drag_rect, maximize_rect) == HTMAXBUTTON
    assert title_bar_hit_test(QPoint(700, 115), drag_rect, maximize_rect) is None


def test_native_snap_style_restores_windows_resize_and_window_capabilities():
    style = native_snap_window_style(0)

    assert style & WS_THICKFRAME
    assert style & WS_MAXIMIZEBOX
    assert style & WS_MINIMIZEBOX
    assert style & WS_SYSMENU
