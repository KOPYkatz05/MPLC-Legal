from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QStackedWidget,
)

from ui.pages.dashboard_page import (
    DashboardPage,
)

from ui.pages.missionaries_page import (
    MissionariesPage,
)

from ui.pages.missionary_detail_page import (
    MissionaryDetailPage,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Mission Legal Tracker"
        )

        self.resize(1400, 900)

        self.setup_ui()

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

        # ==========================================
        # Pages
        # ==========================================

        self.stack = QStackedWidget()

        self.dashboard_page = DashboardPage(self)

        missionaries_page = MissionariesPage(self)

        self.detail_page = MissionaryDetailPage(self)

        self.stack.addWidget(self.dashboard_page)

        self.stack.addWidget(missionaries_page)

        self.stack.addWidget(self.detail_page)

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

    def _on_nav_changed(self, index):
        self.stack.setCurrentIndex(index)
