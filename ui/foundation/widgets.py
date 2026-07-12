from dataclasses import dataclass
import ctypes
import sys

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.foundation.fluent import create_button
from ui.foundation.fluent import CardWidget, SimpleCardWidget, fluent_icon
from ui.foundation.icons import app_icon, lucide_icon


WM_SYSCOMMAND = 0x0112
SC_MOVE = 0xF010
HTCAPTION = 2


def start_native_system_move(window):
    """Begin a real Windows caption drag so snap zones are owned by the OS."""
    if not sys.platform.startswith("win") or window is None:
        return False
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        user32.ReleaseCapture()
        user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MOVE | HTCAPTION, 0)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class NavItem:
    key: str
    title: str
    stack_index: int
    group: str = ""


def divider(object_name="HeaderDivider"):
    line = QFrame()
    line.setObjectName(object_name)
    line.setFixedHeight(1)
    return line


class PageHeader(SimpleCardWidget):
    def __init__(self, title, subtitle="", actions=None, parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(12)
        self.setLayout(layout)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)
        title_stack.addWidget(self.title_label)
        title_stack.addWidget(self.subtitle_label)

        layout.addLayout(title_stack)
        layout.addStretch()

        self.actions = []
        for action in actions or []:
            self.add_action(action)

    def add_action(self, widget):
        self.layout().addWidget(widget)
        self.actions.append(widget)

    def set_title(self, title):
        self.title_label.setText(title)

    def set_subtitle(self, subtitle):
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))


class FilterBar(SimpleCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterBar")
        self.layout_ = QHBoxLayout()
        self.layout_.setContentsMargins(18, 12, 18, 12)
        self.layout_.setSpacing(12)
        self.setLayout(self.layout_)

    def add_filter(self, widget, stretch=0):
        self.layout_.addWidget(widget, stretch=stretch)

    def add_spacer(self):
        self.layout_.addStretch()


class SectionTitle(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(0)
        self.setLayout(layout)
        label = QLabel(text)
        label.setObjectName("SectionHeader")
        layout.addWidget(label)
        layout.addStretch()


class StatCard(SimpleCardWidget):
    def __init__(
        self,
        value,
        title,
        subtitle="",
        accent="#0EA5AC",
        color=None,
        parent=None,
    ):
        super().__init__(parent)
        if color:
            accent = color
        self.setObjectName("StatCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(108)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(3)
        self.setLayout(layout)

        self.value_label = QLabel(str(value))
        self.value_label.setObjectName("StatCount")
        palette = self.value_label.palette()
        palette.setColor(QPalette.WindowText, QColor(accent))
        self.value_label.setPalette(palette)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("StatTitle")
        self.title_label.setWordWrap(True)

        layout.addWidget(self.value_label)
        layout.addWidget(self.title_label)

        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("StatSubtitle")
            layout.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None

        layout.addStretch()

    def setValue(self, value):
        self.value_label.setText(str(value))

    def setTitle(self, title):
        self.title_label.setText(title)

    def setSubtitle(self, subtitle):
        if self.subtitle_label is None:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("StatSubtitle")
            self.layout().insertWidget(
                self.layout().count() - 1,
                self.subtitle_label,
            )
        else:
            self.subtitle_label.setText(subtitle)


class DialogFooter(SimpleCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DialogFooter")
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self.setLayout(layout)
        layout.addStretch()

    def add_action(self, button):
        self.layout().addWidget(button)


class _AppTitleDragRegion(QFrame):
    def __init__(self, title_bar, parent=None):
        super().__init__(parent)
        self.title_bar = title_bar
        self.setObjectName("AppTitleDragRegion")
        self.setCursor(Qt.ArrowCursor)
        self._drag_start_global = None
        self._drag_start_frame = None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        window = self.window()
        self._drag_start_global = self._event_global_position(event)
        self._drag_start_frame = window.frameGeometry().topLeft()

        started = start_native_system_move(window)
        handle = window.windowHandle() if window is not None else None
        if not started and handle is not None and hasattr(handle, "startSystemMove"):
            try:
                started = bool(handle.startSystemMove())
            except Exception:
                started = False
        if started:
            self._drag_start_global = None
            self._drag_start_frame = None
        event.accept()

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.LeftButton
            and self._drag_start_global is not None
            and self._drag_start_frame is not None
        ):
            window = self.window()
            current_global = self._event_global_position(event)
            delta = current_global - self._drag_start_global
            window.move(self._drag_start_frame + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_global = None
        self._drag_start_frame = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.title_bar.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _event_global_position(event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        return QPoint()


class AppTitleBar(QFrame):
    def __init__(self, app_title, parent=None):
        super().__init__(parent)
        self.setObjectName("AppTitleBar")
        self.setFixedHeight(34)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self.drag_region = _AppTitleDragRegion(self, self)
        drag_layout = QHBoxLayout()
        drag_layout.setContentsMargins(0, 0, 0, 0)
        drag_layout.setSpacing(0)
        self.drag_region.setLayout(drag_layout)

        self.drag_affordance = QLabel(self.drag_region)
        self.drag_affordance.setObjectName("AppTitleDragAffordance")
        self.drag_affordance.setFixedSize(55, 34)
        self.drag_affordance.setAlignment(Qt.AlignCenter)
        self.drag_affordance.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.drag_affordance.setToolTip(app_title)
        self.drag_affordance.setAccessibleName(app_title)
        icon = lucide_icon("grip-horizontal", size=16, color="#A1A1AA")
        if icon is not None and not icon.isNull():
            self.drag_affordance.setPixmap(icon.pixmap(QSize(16, 16)))
        else:
            self.drag_affordance.setText("...")
        drag_layout.addWidget(self.drag_affordance)
        drag_layout.addStretch()
        layout.addWidget(self.drag_region, stretch=1)

        self.minimize_button = self._make_window_button(
            "minus",
            "Minimize",
            self._minimize_window,
        )
        self.maximize_button = self._make_window_button(
            "square",
            "Maximize",
            self.toggle_maximized,
        )
        self.close_button = self._make_window_button(
            "x",
            "Close",
            self._close_window,
            object_name="AppWindowCloseButton",
        )

        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)
        self.refresh_maximize_state()

    @staticmethod
    def _global_widget_rect(widget):
        if widget is None or not widget.isVisible():
            return QRect()
        return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())

    def global_drag_rect(self):
        return self._global_widget_rect(self.drag_region)

    def global_maximize_rect(self):
        return self._global_widget_rect(self.maximize_button)

    def _make_window_button(
        self,
        icon_name,
        tooltip,
        callback,
        object_name="AppWindowControlButton",
    ):
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setFixedSize(34, 30)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(True)
        icon = lucide_icon(icon_name, size=16, color="#52525B")
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
        else:
            button.setText(tooltip[:1])
        button.clicked.connect(callback)
        return button

    def _minimize_window(self):
        self.window().showMinimized()

    def _close_window(self):
        self.window().close()

    def toggle_maximized(self):
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
        self.refresh_maximize_state()

    def refresh_maximize_state(self):
        if not hasattr(self, "maximize_button"):
            return
        maximized = self.window().isMaximized()
        tooltip = "Restore" if maximized else "Maximize"
        self.maximize_button.setToolTip(tooltip)
        self.maximize_button.setAccessibleName(tooltip)
        icon_name = "copy" if maximized else "square"
        icon = lucide_icon(icon_name, size=16, color="#52525B")
        if icon is not None and not icon.isNull():
            self.maximize_button.setIcon(icon)


class PillActionButton(QFrame):
    clicked = Signal()

    def __init__(
        self,
        label,
        subtitle="",
        actions=None,
        accent=None,
        leading_icon=None,
        leading_icon_color="#DC2626",
        drag_payload=None,
        drag_mime_type="application/x-pill-drag",
        drag_preview_widget=None,
        object_name="PillActionButton",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._drag_payload = drag_payload
        self._drag_mime_type = drag_mime_type
        self._drag_preview_widget = drag_preview_widget or self
        self._drag_start_pos = None
        self._drag_active = False
        self._drag_watchers = []
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(31, 41, 55, 0))
        self.setGraphicsEffect(self._shadow)

        layout = QHBoxLayout()
        layout.setContentsMargins(16, 7, 10, 7)
        layout.setSpacing(10)
        self.setLayout(layout)

        if accent:
            accent_dot = QFrame(self)
            accent_dot.setObjectName("PillActionAccent")
            accent_dot.setFixedSize(8, 8)
            accent_dot.setStyleSheet(
                f"QFrame#PillActionAccent {{ background-color: {accent}; }}"
            )
            layout.addWidget(accent_dot, alignment=Qt.AlignVCenter)
            self._drag_watchers.append(accent_dot)

        if leading_icon:
            icon_label = QLabel(self)
            icon_label.setObjectName("PillActionLeadingIcon")
            icon_names = (
                list(leading_icon)
                if isinstance(leading_icon, (list, tuple))
                else [leading_icon]
            )
            icon = self._icon_from_names(icon_names, color=leading_icon_color)
            if icon is not None and not icon.isNull():
                icon_label.setPixmap(icon.pixmap(QSize(14, 14)))
                icon_label.setFixedSize(14, 14)
                icon_label.setMinimumSize(14, 14)
                layout.addWidget(icon_label, alignment=Qt.AlignVCenter)
                self._drag_watchers.append(icon_label)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(1)
        layout.addLayout(text_stack, stretch=1)

        self.label = QLabel(label, self)
        self.label.setObjectName("PillActionLabel")
        self.label.setWordWrap(False)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        text_stack.addWidget(self.label)
        self._drag_watchers.append(self.label)

        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("PillActionSubtitle")
        self.subtitle.setWordWrap(False)
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.subtitle.setVisible(bool(subtitle))
        text_stack.addWidget(self.subtitle)
        self._drag_watchers.append(self.subtitle)

        if self._drag_payload is not None:
            self._install_drag_filters()

        self.action_buttons = []
        for action in actions or []:
            button = self._make_icon_button(action)
            layout.addWidget(button, alignment=Qt.AlignVCenter)
            self.action_buttons.append(button)

    def _install_drag_filters(self):
        for widget in [self, *self._drag_watchers]:
            if widget is not None:
                widget.installEventFilter(self)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self.property("compactLayout"):
            # Board cards may be placed in narrow responsive columns. Their
            # labels are elided by the layout, so text length must not impose a
            # page-wide minimum width.
            return QSize(0, hint.height())
        return hint

    def _start_drag(self, source_widget, point):
        payload = self._drag_payload() if callable(self._drag_payload) else self._drag_payload
        if payload is None:
            return False

        mime = QMimeData()
        mime.setData(self._drag_mime_type, str(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        preview_widget = self._drag_preview_widget or self
        pixmap = preview_widget.grab()
        if pixmap.isNull():
            pixmap = QPixmap(preview_widget.size())
            pixmap.fill(Qt.transparent)
            preview_widget.render(pixmap)
        if not pixmap.isNull():
            padded = QPixmap(pixmap.width() + 18, pixmap.height() + 18)
            padded.fill(Qt.transparent)
            painter = QPainter(padded)
            painter.setRenderHint(QPainter.Antialiasing, True)
            shadow_path = QPainterPath()
            radius = max(
                1.0,
                min(24.0, pixmap.width() / 2.0, pixmap.height() / 2.0),
            )
            shadow_path.addRoundedRect(5, 6, pixmap.width(), pixmap.height(), radius, radius)
            painter.fillPath(shadow_path, QColor(15, 23, 42, 26))
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            pixmap = padded
        drag.setPixmap(pixmap)
        try:
            hotspot = source_widget.mapTo(preview_widget, point)
        except Exception:
            hotspot = preview_widget.rect().center()
        drag.setHotSpot(hotspot)
        self._drag_active = True
        was_visible = self.isVisible()
        if was_visible:
            self.setVisible(False)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            if was_visible:
                self.setVisible(True)
            self._drag_active = False
            self._drag_start_pos = None
        return True

    def _make_icon_button(self, action):
        name = action.get("icon") or ""
        fallback_icons = action.get("fallback_icons") or []
        fallback_text = action.get("fallback") or action.get("text") or ""
        tooltip = action.get("tooltip") or action.get("text") or fallback_text
        callback = action.get("callback")
        menu_items = action.get("menu") or []

        button = QToolButton(self)
        button.setObjectName("PillActionIconButton")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(26, 26)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(True)
        icon = self._icon_from_names([name, *fallback_icons])
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(18, 18))
        else:
            button.setText(fallback_text)
        if menu_items:
            menu = QMenu(button)
            menu.setObjectName(action.get("menu_object_name") or "WorkspaceTileContextMenu")
            for item in menu_items:
                menu_action = menu.addAction(item.get("text") or item.get("tooltip") or "")
                menu_icon = self._icon_from_names(
                    [item.get("icon") or "", *(item.get("fallback_icons") or [])]
                )
                if menu_icon is not None and not menu_icon.isNull():
                    menu_action.setIcon(menu_icon)
                item_callback = item.get("callback")
                if item_callback is not None:
                    menu_action.triggered.connect(
                        lambda checked=False, fn=item_callback: fn()
                    )
            button._popup_menu = menu
            button.clicked.connect(
                lambda checked=False, btn=button, popup=menu: popup.popup(
                    btn.mapToGlobal(btn.rect().bottomLeft())
                )
            )
        if callback is not None:
            button.clicked.connect(lambda checked=False, fn=callback: fn())
        return button

    def _icon_from_names(self, names, color="#6B7280"):
        for icon_name in names:
            if not icon_name:
                continue
            icon = lucide_icon(icon_name, size=18, color=color)
            if icon is not None and not icon.isNull():
                return icon
        return None

    def eventFilter(self, obj, event):
        if self._drag_payload is not None and obj in {self, *self._drag_watchers}:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_start_pos = event.position().toPoint()
            elif (
                event.type() == QEvent.MouseMove
                and event.buttons() & Qt.LeftButton
                and self._drag_start_pos is not None
                and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
                >= 8
            ):
                if self._start_drag(obj, event.position().toPoint()):
                    return True
            elif event.type() == QEvent.MouseButtonRelease and self._drag_active:
                self._drag_start_pos = None
                self._drag_active = False
                return True
        return super().eventFilter(obj, event)

    def mouseReleaseEvent(self, event):
        if self._drag_active:
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(0, 0, 0, 26))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(31, 41, 55, 0))
        super().leaveEvent(event)


def create_pill_action_button(
    label,
    subtitle="",
    actions=None,
    accent=None,
    leading_icon=None,
    leading_icon_color="#DC2626",
    drag_payload=None,
    drag_mime_type="application/x-pill-drag",
    drag_preview_widget=None,
    object_name="PillActionButton",
    parent=None,
):
    return PillActionButton(
        label,
        subtitle=subtitle,
        actions=actions,
        accent=accent,
        leading_icon=leading_icon,
        leading_icon_color=leading_icon_color,
        drag_payload=drag_payload,
        drag_mime_type=drag_mime_type,
        drag_preview_widget=drag_preview_widget,
        object_name=object_name,
        parent=parent,
    )


class AppShell(QWidget):
    navigation_changed = Signal(str, int)

    def __init__(self, app_title, parent=None):
        super().__init__(parent)
        self.setObjectName("CentralWidget")
        self._items = []
        self._buttons = {}
        self._system_section_started = False
        self._icon_names = {
            "dashboard": ("VIEW_DASHBOARD", "HOME"),
            "missionaries": ("PEOPLE", "CONTACT"),
            "office_work": ("BULLETS", "EDIT"),
            "appointments": ("CALENDAR",),
            "reports": ("BAR_CHART", "DOCUMENT"),
            "trash": ("DELETE",),
            "workspaces": ("PACKAGE", "FOLDER"),
            "settings": ("SETTING",),
        }

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

        self.title_bar = AppTitleBar(app_title, self)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        body.setObjectName("AppShellBody")
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body.setLayout(body_layout)
        root.addWidget(body, stretch=1)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("FluentSidebar")
        self.sidebar.setFixedWidth(71)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar_layout.setContentsMargins(8, 8, 8, 8)
        self.sidebar_layout.setSpacing(0)
        self.sidebar.setLayout(self.sidebar_layout)

        self.menu_button = QToolButton(self.sidebar)
        self.menu_button.setObjectName("SidebarMenuButton")
        self.menu_button.setFixedSize(55, 55)
        self.menu_button.setToolTip(app_title)
        self.menu_button.setAccessibleName(app_title)
        self.menu_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.menu_button.setIcon(
            app_icon("sidebar.menu", size=24, fallback=self._line_icon("menu"))
        )
        self.menu_button.setIconSize(QSize(20, 20))
        self.menu_button.setAutoRaise(True)
        self.sidebar_layout.addWidget(self.menu_button)
        self.sidebar_layout.addWidget(self._nav_separator())

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentStack")
        # QStackedWidget normally propagates the largest minimum-size hint from
        # every page, including hidden pages. That can prevent Windows from
        # snapping the main window onto smaller displays. Let the shell shrink
        # and leave overflow/scrolling decisions to the active page.
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.stack, stretch=1)

        self.sidebar_layout.addStretch()

    def add_nav_item(self, key, title, stack_index, group=""):
        if group and self._items and self._items[-1].group != group:
            insert_at = max(1, self.sidebar_layout.count() - 1)
            self.sidebar_layout.insertWidget(insert_at, self._nav_separator())

        if group == "System" and not self._system_section_started:
            insert_at = max(1, self.sidebar_layout.count() - 1)
            self.sidebar_layout.insertStretch(insert_at, 1)
            self._system_section_started = True

        button = QToolButton(self.sidebar)
        button.setCheckable(True)
        button.setObjectName("SidebarNavButton")
        button.setFixedSize(55, 55)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setText(self._fallback_icon_text(key, title))
        icon = self._nav_icon(key)
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(20, 20))
            button.setText("")
        button.clicked.connect(
            lambda checked=False, item_key=key: self.set_current_key(item_key)
        )
        self._button_group.addButton(button)

        insert_at = max(1, self.sidebar_layout.count() - 1)
        self.sidebar_layout.insertWidget(insert_at, button)
        self._buttons[key] = button
        self._items.append(NavItem(key, title, stack_index, group))

    def set_current_key(self, key):
        item = next((nav for nav in self._items if nav.key == key), None)
        if not item:
            return
        self.stack.setCurrentIndex(item.stack_index)
        self._buttons[key].setChecked(True)
        self.navigation_changed.emit(item.key, item.stack_index)

    def set_nav_title(self, key, title):
        if key in self._buttons:
            self._buttons[key].setToolTip(title)

    def _nav_icon(self, key):
        icon = app_icon(
            f"sidebar.{key}",
            fallback_names=self._icon_names.get(key, ()),
            size=24,
        )
        if icon is not None:
            return icon

        for name in self._icon_names.get(key, ()):
            icon = fluent_icon(name)
            if hasattr(icon, "icon"):
                try:
                    return icon.icon()
                except Exception:
                    continue
            if icon is not None:
                return icon
        return self._line_icon(key)

    @staticmethod
    def _line_icon(key):
        icon_key = "list" if key == "office_work" else key
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#242424"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if icon_key == "menu":
            for y in (7, 12, 17):
                painter.drawLine(QPointF(7, y), QPointF(17, y))
        elif icon_key == "dashboard":
            for rect in (
                QRectF(6, 6, 4.8, 4.8),
                QRectF(13.2, 6, 4.8, 4.8),
                QRectF(6, 13.2, 4.8, 4.8),
                QRectF(13.2, 13.2, 4.8, 4.8),
            ):
                painter.drawRoundedRect(rect, 1.2, 1.2)
        elif icon_key == "missionaries":
            painter.drawEllipse(QPointF(10, 8), 2.4, 2.4)
            painter.drawEllipse(QPointF(16, 9), 2.0, 2.0)
            painter.drawArc(QRectF(6.5, 12, 7, 6), 20 * 16, 140 * 16)
            painter.drawArc(QRectF(12.5, 13, 6, 5), 20 * 16, 140 * 16)
        elif icon_key == "list":
            for y in (7, 12, 17):
                painter.drawPoint(QPointF(6.5, y))
                painter.drawLine(QPointF(10, y), QPointF(18, y))
        elif icon_key == "appointments":
            painter.drawRoundedRect(QRectF(6, 7, 12, 11), 1.6, 1.6)
            painter.drawLine(QPointF(6, 10), QPointF(18, 10))
            painter.drawLine(QPointF(9, 5.5), QPointF(9, 8))
            painter.drawLine(QPointF(15, 5.5), QPointF(15, 8))
        elif icon_key == "workspaces":
            painter.drawPolygon(
                [
                    QPointF(12, 5.5),
                    QPointF(18, 9),
                    QPointF(18, 15.5),
                    QPointF(12, 19),
                    QPointF(6, 15.5),
                    QPointF(6, 9),
                ]
            )
            painter.drawLine(QPointF(12, 12), QPointF(12, 19))
            painter.drawLine(QPointF(6.5, 9.2), QPointF(12, 12))
            painter.drawLine(QPointF(17.5, 9.2), QPointF(12, 12))
        elif icon_key == "reports":
            painter.drawLine(QPointF(7, 18), QPointF(17, 18))
            painter.drawLine(QPointF(8, 16), QPointF(8, 12))
            painter.drawLine(QPointF(12, 16), QPointF(12, 7))
            painter.drawLine(QPointF(16, 16), QPointF(16, 10))
        elif icon_key == "trash":
            painter.drawLine(QPointF(8, 8), QPointF(16, 8))
            painter.drawLine(QPointF(10, 6), QPointF(14, 6))
            painter.drawRoundedRect(QRectF(8.5, 9, 7, 9), 1.4, 1.4)
        elif icon_key == "settings":
            painter.drawEllipse(QPointF(12, 12), 5.2, 5.2)
            painter.drawEllipse(QPointF(12, 12), 1.8, 1.8)
            for x1, y1, x2, y2 in (
                (12, 5, 12, 7),
                (12, 17, 12, 19),
                (5, 12, 7, 12),
                (17, 12, 19, 12),
            ):
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        else:
            painter.drawEllipse(QPointF(12, 12), 5.5, 5.5)

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _fallback_icon_text(key, title):
        return {
            "dashboard": "D",
            "missionaries": "M",
            "office_work": "W",
            "appointments": "C",
            "reports": "R",
            "trash": "T",
            "workspaces": "B",
            "settings": "S",
        }.get(key, (title or "?")[:1])

    @staticmethod
    def _nav_separator():
        line = QFrame()
        line.setObjectName("SidebarSeparator")
        line.setFixedHeight(17)
        return line


def configure_data_table(
    table: QTableWidget,
    resize_modes,
    selection_mode=QAbstractItemView.SingleSelection,
    sorting=True,
):
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(selection_mode)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setSortingEnabled(sorting)
    table.setWordWrap(False)

    header_view = table.horizontalHeader()
    for column, mode in resize_modes.items():
        header_view.setSectionResizeMode(column, mode)

    table.verticalHeader().setDefaultSectionSize(42)
    return table
