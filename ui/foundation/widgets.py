from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.foundation.fluent import create_button
from ui.foundation.fluent import CardWidget, SimpleCardWidget


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
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))

        layout = QHBoxLayout()
        layout.setContentsMargins(32, 18, 32, 18)
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
        self.layout_.setContentsMargins(32, 12, 32, 12)
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
        accent="#2563EB",
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

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("FluentSidebar")
        self.sidebar.setFixedWidth(238)
        self.sidebar_layout = QVBoxLayout()
        self.sidebar_layout.setContentsMargins(12, 16, 12, 16)
        self.sidebar_layout.setSpacing(4)
        self.sidebar.setLayout(self.sidebar_layout)

        brand = QLabel(app_title)
        brand.setObjectName("SidebarBrand")
        brand.setWordWrap(True)
        self.sidebar_layout.addWidget(brand)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentStack")

        root.addWidget(self.sidebar)
        root.addWidget(self.stack, stretch=1)

        self.sidebar_layout.addStretch()

    def add_nav_item(self, key, title, stack_index, group=""):
        if group and (
            not self._items or self._items[-1].group != group
        ):
            label = QLabel(group.upper())
            label.setObjectName("SidebarGroupLabel")
            insert_at = max(1, self.sidebar_layout.count() - 1)
            self.sidebar_layout.insertWidget(insert_at, label)

        button = QPushButton(title)
        button.setCheckable(True)
        button.setObjectName("SidebarNavButton")
        button.setFixedHeight(38)
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
            self._buttons[key].setText(title)


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
