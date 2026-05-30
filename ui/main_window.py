from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QStackedWidget,
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

        self.setCentralWidget(
            central_widget
        )

        layout = QHBoxLayout()

        central_widget.setLayout(layout)

        # Sidebar
        self.sidebar = QListWidget()

        self.sidebar.addItem("Dashboard")
        self.sidebar.addItem("Missionaries")

        self.sidebar.setFixedWidth(200)

        # Pages
        self.stack = QStackedWidget()

        dashboard_page = QWidget()

        missionaries_page = (
            MissionariesPage(self)
        )

        self.detail_page = (
            MissionaryDetailPage(self)
        )

        # Add pages
        self.stack.addWidget(
            dashboard_page
        )

        self.stack.addWidget(
            missionaries_page
        )

        self.stack.addWidget(
            self.detail_page
        )

        # Sidebar navigation
        self.sidebar.currentRowChanged.connect(
            self.stack.setCurrentIndex
        )

        self.sidebar.setCurrentRow(0)

        # Layout
        layout.addWidget(self.sidebar)

        layout.addWidget(self.stack)