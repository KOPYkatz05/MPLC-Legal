from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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


class AppShell(QWidget):
    navigation_changed = Signal(str, int)

    def __init__(self, app_title, parent=None):
        super().__init__(parent)
        self.setObjectName("CentralWidget")
        self._items = []
        self._buttons = {}
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

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

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
        self.menu_button.setIcon(self._line_icon("menu"))
        self.menu_button.setIconSize(QSize(20, 20))
        self.menu_button.setAutoRaise(True)
        self.sidebar_layout.addWidget(self.menu_button)
        self.sidebar_layout.addWidget(self._nav_separator())

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentStack")

        root.addWidget(self.sidebar)
        root.addWidget(self.stack, stretch=1)

        self.sidebar_layout.addStretch()

    def add_nav_item(self, key, title, stack_index, group=""):
        if group and self._items and self._items[-1].group != group:
            insert_at = max(1, self.sidebar_layout.count() - 1)
            self.sidebar_layout.insertWidget(insert_at, self._nav_separator())

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
