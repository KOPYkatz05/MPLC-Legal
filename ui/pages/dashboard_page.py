from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette

from services.dashboard_service import (
    DashboardService,
)
from ui.foundation import (
    PageHeader,
    SectionTitle as SectionHeader,
    StatCard,
    create_button,
    create_scroll_area,
    divider,
)
from ui.foundation.fluent import SimpleCardWidget

from utils.constants import WORKFLOW_STAGES

from utils.logger import logger


# ==========================================
# COLOR PALETTE
# ==========================================

STAGE_COLORS = {
    "INTERPOL": "#7C3AED",
    "CARNET DE EXTRANJERIA": "#D97706",
    "PRORROGA": "#059669",
    "CANCELACION": "#DC2626",
}

STAGE_LABELS = {
    "INTERPOL": "Interpol",
    "CARNET DE EXTRANJERIA": "Carnet de\nExtranjería",
    "PRORROGA": "Prórroga",
    "CANCELACION": "Cancelación",
}


# ==========================================
# COLUMN HEADER ROW
# ==========================================

class ColumnHeaderRow(QFrame):
    def __init__(self, columns, parent=None):
        super().__init__(parent)

        self.setObjectName("ColumnHeaderRow")

        layout = QHBoxLayout()

        layout.setContentsMargins(20, 8, 20, 8)

        layout.setSpacing(16)

        self.setLayout(layout)

        for text, stretch in columns:
            lbl = QLabel(text.upper())

            lbl.setObjectName("ColHeaderLabel")

            layout.addWidget(lbl, stretch=stretch)


# ==========================================
# TABLE ROW
# ==========================================

class TableRow(QFrame):
    def __init__(self, alternate=False, parent=None):
        super().__init__(parent)

        self.setObjectName(
            "TableRowAlt" if alternate else "TableRow"
        )

        self.layout_ = QHBoxLayout()

        self.layout_.setContentsMargins(20, 12, 20, 12)

        self.layout_.setSpacing(16)

        self.setLayout(self.layout_)

    def add_cell(
        self,
        text,
        stretch=1,
        bold=False,
        color=None,
        align=Qt.AlignVCenter,
        word_wrap=False,
    ):
        lbl = QLabel(text)

        lbl.setObjectName("RowText")

        lbl.setAlignment(align)

        lbl.setWordWrap(word_wrap)

        if bold:
            font = QFont(lbl.font())
            font.setWeight(QFont.DemiBold)
            lbl.setFont(font)

        if color:
            palette = lbl.palette()
            palette.setColor(QPalette.WindowText, QColor(color))
            lbl.setPalette(palette)

        self.layout_.addWidget(lbl, stretch=stretch)


# ==========================================
# LIST CARD (container for table rows)
# ==========================================

class ListCard(SimpleCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("ListCard")

        self._layout = QVBoxLayout()

        self._layout.setContentsMargins(0, 0, 0, 0)

        self._layout.setSpacing(0)

        self.setLayout(self._layout)

    def add_widget(self, widget):
        self._layout.addWidget(widget)

    def add_empty(self, text):
        lbl = QLabel(f"  {text}")

        lbl.setObjectName("EmptyLabel")

        self._layout.addWidget(lbl)


# ==========================================
# DASHBOARD PAGE
# ==========================================

class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.service = DashboardService()

        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        # ======================================
        # Top header bar
        # ======================================

        header_bar = QFrame()

        header_bar.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(32, 20, 32, 20)

        header_bar.setLayout(header_layout)

        title = QLabel("Dashboard")

        title.setObjectName("PageTitle")

        self.refresh_btn = create_button(
            "↻   Refresh",
            "secondary",
        )

        self.refresh_btn.setObjectName("RefreshButton")

        self.refresh_btn.clicked.connect(
            self.load_data
        )

        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(self.refresh_btn)

        outer.addWidget(header_bar)

        # ======================================
        # Divider
        # ======================================

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # ======================================
        # Scrollable content area
        # ======================================

        scroll = create_scroll_area()

        scroll.setObjectName("DashboardScroll")

        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.content_widget = QWidget()

        self.content_widget.setObjectName(
            "DashboardContent"
        )

        self.content_layout = QVBoxLayout()

        self.content_layout.setContentsMargins(
            32, 24, 32, 32
        )

        self.content_layout.setSpacing(20)

        self.content_widget.setLayout(
            self.content_layout
        )

        scroll.setWidget(self.content_widget)

        outer.addWidget(scroll, stretch=1)

        self.load_data()

    def load_data(self):
        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        data = self.service.get_summary()

        self._build_stat_cards(data)

        self._build_expiring_section(
            data["expiring"]
        )

        self._build_missing_section(
            data["missing_docs"]
        )

        self.content_layout.addStretch()

        logger.info("Dashboard data loaded")

    # ==========================================
    # STAT CARDS
    # ==========================================

    def _build_stat_cards(self, data):
        self.content_layout.addWidget(
            SectionHeader("Overview")
        )

        row = QHBoxLayout()

        row.setSpacing(16)

        # Total card
        total_card = StatCard(
            data["total"],
            "Active Missionaries",
            color="#3B82F6",
        )

        row.addWidget(total_card)

        # Per-stage cards
        for stage in WORKFLOW_STAGES:
            count = data["stage_counts"].get(stage, 0)

            card = StatCard(
                count,
                STAGE_LABELS.get(stage, stage),
                color=STAGE_COLORS.get(
                    stage,
                    "#6B7280",
                ),
            )

            row.addWidget(card)

        wrapper = QWidget()

        wrapper.setLayout(row)

        self.content_layout.addWidget(wrapper)

    # ==========================================
    # EXPIRING DOCUMENTS
    # ==========================================

    def _build_expiring_section(self, expiring):
        self.content_layout.addWidget(
            SectionHeader("⚠   Expiring Within 60 Days")
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                ("Missionary", 3),
                ("Document", 3),
                ("Expiry Date", 2),
                ("Days Remaining", 2),
            ])
        )

        if not expiring:
            card.add_empty(
                "No documents expiring within 60 days."
            )

        else:
            for i, item in enumerate(expiring):
                days = item["days_left"]

                if days < 0:
                    day_color = "#DC2626"
                    urgency = "Expired"

                elif days <= 14:
                    day_color = "#DC2626"
                    urgency = f"{days} days"

                elif days <= 30:
                    day_color = "#D97706"
                    urgency = f"{days} days"

                else:
                    day_color = "#059669"
                    urgency = f"{days} days"

                row = TableRow(alternate=(i % 2 == 1))

                row.add_cell(
                    item["name"],
                    stretch=3,
                    bold=True,
                )

                row.add_cell(
                    item["field_label"],
                    stretch=3,
                )

                row.add_cell(
                    item["date"].strftime("%b %d, %Y"),
                    stretch=2,
                )

                row.add_cell(
                    urgency,
                    stretch=2,
                    bold=True,
                    color=day_color,
                )

                card.add_widget(row)

        self.content_layout.addWidget(card)

    # ==========================================
    # MISSING DOCUMENTS
    # ==========================================

    def _build_missing_section(self, missing_docs):
        self.content_layout.addWidget(
            SectionHeader("✗   Missing Required Documents")
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                ("Missionary", 2),
                ("Missing Documents", 5),
            ])
        )

        if not missing_docs:
            card.add_empty(
                "All missionaries have their "
                "required documents."
            )

        else:
            for i, item in enumerate(missing_docs):
                row = TableRow(alternate=(i % 2 == 1))

                row.add_cell(
                    item["name"],
                    stretch=2,
                    bold=True,
                    align=Qt.AlignTop | Qt.AlignLeft,
                )

                lines = []

                for doc in item["missing"]:
                    stage = doc["stage"]
                    label = doc["label"]

                    lines.append(
                        f"[{stage}]  {label}"
                    )

                row.add_cell(
                    "\n".join(lines),
                    stretch=5,
                    word_wrap=True,
                    color="#71717A",
                )

                card.add_widget(row)

        self.content_layout.addWidget(card)

    # ==========================================
    # AUTO-REFRESH ON SHOW
    # ==========================================

    def showEvent(self, event):
        super().showEvent(event)

        self.load_data()
